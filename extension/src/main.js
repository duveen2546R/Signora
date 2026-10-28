/**
 * Orchestrator. Runs in the isolated content-script world on a YouTube watch page.
 *
 * Sequence: find the <video> -> check the backend -> get English captions -> convert to VTT ->
 * POST to the existing /api/v1/video-plans -> poll until ready -> hand the returned timed units
 * to the unmodified YouTubeSignScheduler, with the page's <video> adapted to its media contract
 * and an AvatarAdapter standing in for playback.
 *
 * Deliberately absent: any word/phrase matching. Resolving captions to glosses, multi-word
 * phrases, repeated occurrences, fingerspelling and unsupported-word reporting all already live
 * in backend/app/services/video_plan_service.py, and duplicating that here is exactly the
 * competing planner the task rules out.
 */

import { config, loadConfig, log, warn } from './config.js'
import { CaptionsUnavailableError, PageBridge, discoverCaptions } from './captions/discover.js'
import { timedTextToVtt } from './captions/convert.js'
import { WATCHED_EVENTS, createYouTubeMedia, videoEventToPlayerState } from './media/youtube-media.js'
import { MockAvatarAdapter } from './avatar/adapter.js'
import { UnityIframeAvatarAdapter } from './avatar/unity-iframe.js'
import { Overlay } from './overlay/overlay.js'
import {
  describeReadiness, diffNewlyReady, isPlanTerminal, progressSummary, summarizeIssues,
} from './plan/progressive.js'
import YouTubeSignScheduler, { YT_STATE } from '../vendor/YouTubeSignScheduler.js'

/** Promise-wrapped chrome.runtime.sendMessage; rejects with the worker's error text. */
function callBackground(type, payload) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type, payload }, (reply) => {
      const lastError = chrome.runtime.lastError
      if (lastError) { reject(new Error(lastError.message)); return }
      if (!reply) { reject(new Error('No reply from the extension service worker.')); return }
      if (!reply.ok) {
        const error = new Error(reply.error)
        error.offline = reply.offline
        reject(error)
        return
      }
      resolve(reply.value)
    })
  })
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function videoId() {
  try { return new URL(location.href).searchParams.get('v') || '' } catch { return '' }
}

async function waitForVideo(timeoutMs = 20000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const video = document.querySelector('#movie_player video, video.html5-main-video, video')
    if (video && Number.isFinite(video.duration)) return video
    if (video && video.readyState > 0) return video
    await sleep(250)
  }
  return document.querySelector('video')
}

export class SignoraSession {
  constructor() {
    this.overlay = null
    this.bridge = null
    this.scheduler = null
    this.adapter = null
    this.media = null
    this.video = null
    this.planId = null
    this.listeners = []
    this.uiTimer = null
    this.videoId = videoId()
    this.unsupported = []
    this.destroyed = false
  }

  // --- lifecycle ---------------------------------------------------------------------------

  async start() {
    await loadConfig()
    const settings = config()

    this.overlay = new Overlay({
      onRetry: () => this.restart(),
      onPickSubtitle: () => this.pickSubtitleFile(),
      onDownloadCaptions: () => this.downloadCaptions(),
    }).mount(settings.overlayExpanded)
    this.overlay.update({ adapterName: settings.avatarAdapter })

    // Progressive plan state. `allUnits` always holds the full, latest-known unit list (every
    // unit's startMs/endMs/text is known immediately after POSTing - only motionAvailable/status
    // trickle in afterwards), so the overlay can describe what's coming even for units the
    // scheduler does not know about yet.
    this.allUnits = []
    this.readyIds = new Set()
    this.planStatusValue = 'pending'
    this.lastVtt = ''

    this.bridge = new PageBridge()
    this.video = await waitForVideo()
    if (!this.video) {
      this.overlay.update({ status: 'no-captions', detail: 'No <video> element found on this page.' })
      return
    }
    this.media = createYouTubeMedia(this.video)

    await this.prepare()
  }

  async prepare() {
    try {
      this.overlay.update({ status: 'checking-backend', detail: '' })
      await callBackground('health')
    } catch (error) {
      this.overlay.update({
        status: 'backend-unavailable',
        detail: error.offline
          ? `Cannot reach ${config().apiBase}. Start the backend: cd backend && uvicorn app.main:app --port 8000`
          : error.message,
      })
      return
    }

    let captions
    try {
      this.overlay.update({ status: 'preparing-captions', detail: '' })
      captions = await discoverCaptions(this.bridge, {
        onStatus: (detail) => this.overlay.update({ detail }),
      })
    } catch (error) {
      const unavailable = error instanceof CaptionsUnavailableError
      this.overlay.update({
        status: 'no-captions',
        detail: `${error.message}${unavailable ? ' Use “Load subtitle file…” to test with a local .vtt/.srt.' : ''}`,
      })
      // The player may still fetch its timed text later - most often because the viewer presses
      // the CC button themselves. Keep listening and continue automatically when it arrives,
      // instead of leaving the panel stuck on an error that a single click has already fixed.
      this.watchForLateCaptions()
      return
    }

    log('captions', captions.format, captions.cues.length, 'cues via', captions.via)
    this.overlay.update({
      detail: `${captions.cues.length} caption cues (${captions.format}, ${captions.track?.kind === 'asr' ? 'auto-generated' : 'manual'}, via ${captions.via})`,
    })
    await this.buildPlan(captions.vtt)
  }

  /**
   * Stay subscribed to the page bridge after a caption failure.
   *
   * YouTube only hands over timed text when its own player asks for it, and the most common way
   * that finally happens is the viewer pressing CC. One listener costs nothing and turns a dead
   * end into "it starts working the moment you turn captions on".
   */
  watchForLateCaptions() {
    if (this.lateCaptionOff) return
    this.lateCaptionOff = this.bridge.onTimedText((payload) => {
      if (this.destroyed || this.planId) return
      let converted
      try {
        converted = timedTextToVtt(payload.body)
      } catch {
        return // empty or unusable body; keep waiting
      }
      this.lateCaptionOff?.()
      this.lateCaptionOff = null
      log('late captions captured after the initial failure')
      this.overlay.update({
        detail: `Captions arrived (${converted.cues.length} cues). Preparing the sign plan…`,
      })
      this.buildPlan(converted.vtt)
    })
  }

  /**
   * POST the VTT and attach a scheduler immediately, without waiting for the whole plan.
   *
   * Measured against the real backend: `prepare_plan` commits each unit to the database as soon
   * as it is decided, and `GET /video-plans/{id}` already reflects that mid-run - unit 0 showed
   * `motionAvailable: true` within 3 s of POSTing, while the overall plan stayed
   * `status: "processing"` for minutes afterwards (one unit's rejected-transition seam search
   * alone measured 31 s). So the fix is entirely client-side: stop waiting for
   * `plan.status === 'ready'` before doing anything. The scheduler is attached straight away with
   * zero units and fed units one at a time as `pollPlanProgress` discovers them ready.
   */
  async buildPlan(vtt) {
    this.lastVtt = vtt
    this.overlay.update({ status: 'preparing-plan', detail: 'Sending captions to the Signora backend…' })
    let plan
    try {
      plan = await callBackground('createVideoPlan', {
        youtubeUrl: location.href.split('&')[0],
        vtt,
        filename: 'captions.vtt',
      })
    } catch (error) {
      this.overlay.update({ status: 'plan-failed', detail: error.message })
      return
    }
    if (this.destroyed) return

    this.planId = plan.id
    this.allUnits = plan.units
    this.readyIds = new Set()
    this.planStatusValue = plan.status

    await this.attachScheduler(plan)
    this.overlay.update({
      status: 'buffering-signs',
      detail: `Preparing the first signs… (${plan.units.length} caption units total)`,
    })
    this.pollPlanProgress(plan.id)
  }

  /**
   * Keep polling after the scheduler is already attached and playable, feeding newly-composed
   * units into it as they arrive and keeping the overlay's coverage/unsupported summary current.
   * Runs until the plan reaches a terminal status; never blocks playback while it runs.
   */
  async pollPlanProgress(planId) {
    const settings = config()
    const deadline = Date.now() + settings.planTimeoutMs
    let interval = settings.planPollMs

    while (!this.destroyed && this.planId === planId) {
      let plan
      try {
        plan = await callBackground('getVideoPlan', planId)
      } catch (error) {
        this.overlay.update({ detail: `Lost contact with the backend while composing: ${error.message}` })
        return
      }
      if (this.destroyed || this.planId !== planId) return

      this.allUnits = plan.units
      this.planStatusValue = plan.status

      const { newlyReady, readyIds } = diffNewlyReady(plan.units, this.readyIds)
      this.readyIds = readyIds
      if (newlyReady.length && this.scheduler) {
        // Mutate the scheduler's own array rather than its constructor argument: the vendored
        // scheduler copies `units` into `this.units` at construction and never looks at the
        // original reference again, but `this.units` itself is a plain, public field. Pushing
        // into it is the whole mechanism that lets later units become playable without
        // reconstructing the scheduler or forking its source.
        this.scheduler.units.push(...newlyReady)
        this.scheduler.units.sort((a, b) => a.startMs - b.startMs)
        log(`${newlyReady.length} unit(s) became playable:`, newlyReady.map((u) => u.glosses).flat())
      }

      const summary = progressSummary(plan.units, this.readyIds)

      if (isPlanTerminal(plan.status)) {
        const { notSigned, fallbackUnits } = summarizeIssues(plan.units)
        this.unsupported = notSigned
        this.overlay.update({ coverage: plan.coverage, unsupported: notSigned, fallbackUnits })
        if (plan.status === 'failed' && summary.ready === 0) {
          this.overlay.update({ status: 'plan-failed', detail: plan.error || 'The sign plan failed.' })
        } else {
          this.overlay.update({
            detail: `${summary.ready}/${summary.total} caption units have composed motion.`,
          })
        }
        return
      }

      this.overlay.update({
        coverage: plan.coverage,
        detail: `Composing in the background… ${summary.ready}/${summary.total} units ready`,
      })

      if (Date.now() > deadline) {
        // The backend may legitimately still be working (compose time for a rejected multi-sign
        // transition has been measured over 30 s for a single unit); slow down rather than give
        // up, so a late unit can still appear if its caption window has not fully passed yet.
        interval = Math.max(interval, 5000)
      }
      await sleep(interval)
    }
  }

  // --- scheduling --------------------------------------------------------------------------

  async attachScheduler(plan) {
    const settings = config()
    // Which adapter is *actually* in use, which is not the configured one if Unity failed and we
    // fell back. The overlay's mock view is driven off this, not off the config.
    this.adapterKind = settings.avatarAdapter === 'unity' ? 'unity' : 'mock'

    const onState = (state) => {
      const patch = {
        progress: state.progress ?? 0,
        activeGloss: state.activeGloss,
        rate: this.media?.getPlaybackRate?.() ?? state.rate ?? 1,
      }
      if (state.playing && !state.paused) patch.status = 'signing'
      this.overlay.update(patch)
      if (this.adapterKind === 'mock') {
        this.overlay.renderMock({
          activeGloss: state.activeGloss, playing: state.playing, paused: state.paused,
        })
      }
    }

    if (settings.avatarAdapter === 'unity') {
      this.adapter = new UnityIframeAvatarAdapter({
        hostUrl: settings.unityHostUrl, mount: this.overlay.avatarMount(), onState,
      })
      try {
        await this.adapter.loadPlan(plan)
      } catch (error) {
        warn('Unity avatar unavailable, falling back to the mock adapter:', error.message)
        this.overlay.update({
          detail: `Unity avatar unavailable (${error.message}) — using the mock adapter.`,
          adapterName: 'mock (unity failed)',
        })
        this.adapter.destroy?.()
        this.adapterKind = 'mock'
        this.adapter = new MockAvatarAdapter({ onState })
        await this.adapter.loadPlan(plan)
        // Unity's iframe may have been mounted before it failed; reclaim the view.
        const mount = this.overlay.avatarMount()
        if (mount) mount.innerHTML = ''
        this.overlay.renderMock({ activeGloss: null, playing: false, paused: false })
      }
    } else {
      this.adapter = new MockAvatarAdapter({ onState })
      await this.adapter.loadPlan(plan)
      this.overlay.renderMock({ activeGloss: null, playing: false, paused: false })
    }

    // The scheduler is used exactly as the Watch page uses it; `loadMotion` routes through the
    // service worker, and `units` starts empty on purpose - see pollPlanProgress() for why. Every
    // other behaviour (play/pause/seek/rate/overrun) is the scheduler's own, untouched logic.
    this.scheduler = new YouTubeSignScheduler({
      media: this.media,
      avatar: this.adapter,
      units: [],
      loadMotion: (unit) => callBackground('getUnitMotion', unit.motionUrl),
      overrunPolicy: settings.overrunPolicy,
      prepareMotion: (motion, unit) => ({
        ...motion,
        // This is a video-caption performance, not a live microphone queue.  Fit the entire
        // composed unit to its source cue so the avatar and spoken words progress together.
        playbackTiming: { targetDurationMs: Math.max(250, unit.endMs - unit.startMs) },
      }),
      onSync: (detail) => this.overlay.update({ detail }),
    })

    this.bindVideoEvents()
    this.scheduler.start()
    // Seed the scheduler with the player's current state so a video already playing is picked up.
    this.scheduler.setPlayerState(this.video.paused ? YT_STATE.PAUSED : YT_STATE.PLAYING)
    this.adapter.setPlaybackRate(this.media.getPlaybackRate())

    this.uiTimer = setInterval(() => this.paintStatus(), 250)
  }

  bindVideoEvents() {
    const add = (target, name, handler) => {
      target.addEventListener(name, handler)
      this.listeners.push(() => target.removeEventListener(name, handler))
    }

    for (const name of WATCHED_EVENTS) {
      add(this.video, name, () => {
        if (name === 'ratechange') {
          const rate = this.media.getPlaybackRate()
          this.adapter?.setPlaybackRate(rate)
          this.overlay.update({ rate })
          return
        }
        if (name === 'seeked') {
          // Not forwarded as a state: the scheduler detects the jump in tick() and resyncs.
          // See media/youtube-media.js for why.
          return
        }
        if (name === 'pause' && !this.media.isPausedByExtension()) {
          this.media.noteExternalPause()
        }
        const state = videoEventToPlayerState(name)
        if (state !== null) this.scheduler?.setPlayerState(state)
      })
    }

    // YouTube is a SPA: navigating to another video reuses the same <video> element.
    const onNavigate = () => {
      const current = videoId()
      if (current && current !== this.videoId) {
        log('navigated to', current, '- restarting session')
        this.restart()
      }
    }
    add(window, 'yt-navigate-finish', onNavigate)
    add(window, 'popstate', onNavigate)
  }

  /**
   * Translate the live media/adapter/plan state into the overlay's status line.
   *
   * Caption and gloss text come from `describeReadiness` against `this.allUnits` - the full,
   * timestamped unit list known since the moment the plan was created - rather than from the
   * scheduler's own unit array, which only ever contains units that have already finished
   * composing. That split is what lets the overlay say "buffering" for a caption whose sign is
   * still being composed, instead of showing nothing at all.
   */
  paintStatus() {
    if (!this.scheduler || !this.adapter) return
    const snapshot = this.adapter.snapshot?.() ?? {}
    const paused = Boolean(this.video?.paused)
    const autoPaused = Boolean(this.scheduler.autoPaused)
    const mediaMs = this.media.getCurrentTime() * 1000
    const readiness = describeReadiness(
      mediaMs, this.allUnits, this.readyIds, this.planStatusValue, config().lookaheadUnits,
    )

    let status
    if (autoPaused) status = 'catch-up'
    else if (this.video?.ended) status = 'ended'
    else if (paused) status = 'paused'
    else if (snapshot.playing) status = 'signing'
    else if (readiness.state === 'buffering-current' || readiness.state === 'buffering-lookahead') {
      status = 'buffering-signs'
    } else status = 'ready'

    const patch = { status, progress: snapshot.progress ?? 0, rate: this.media.getPlaybackRate() }
    if (readiness.unit) {
      patch.caption = readiness.unit.text || ''
      patch.glosses = readiness.unit.glosses || []
      patch.activeGloss = snapshot.activeGloss ?? null
    } else if (readiness.units?.length) {
      // Nothing is current yet, but show what the look-ahead buffer is working on.
      patch.caption = readiness.units[0].text || ''
      patch.glosses = readiness.units[0].glosses || []
      patch.activeGloss = null
    }
    this.overlay.update(patch)

    if (this.adapterKind === 'mock') {
      this.overlay.renderMock({
        activeGloss: snapshot.activeGloss, playing: snapshot.playing, paused: snapshot.paused,
      })
    }
  }

  // --- manual fallback ---------------------------------------------------------------------

  /**
   * Honest fallback when YouTube will not release its timed text: let the user supply the same
   * SRT/VTT the Watch page accepts. Everything downstream is identical, so the scheduler, pause,
   * seek, speed and overrun behaviour stay fully testable.
   */
  pickSubtitleFile() {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.vtt,.srt,text/vtt,application/x-subrip'
    input.style.display = 'none'
    input.addEventListener('change', async () => {
      const file = input.files?.[0]
      input.remove()
      if (!file) return
      try {
        const text = await file.text()
        // A .srt/.vtt goes to the backend unchanged; a JSON3/XML dump is converted first.
        const trimmed = text.trimStart()
        const vtt = (trimmed.startsWith('{') || trimmed.startsWith('<'))
          ? timedTextToVtt(text).vtt
          : text
        this.teardownScheduler()
        this.overlay.update({ detail: `Using local file ${file.name}` })
        await this.buildPlan(vtt)
      } catch (error) {
        this.overlay.update({ status: 'plan-failed', detail: error.message })
      }
    })
    document.documentElement.appendChild(input)
    input.click()
  }

  // --- teardown ----------------------------------------------------------------------------

  teardownScheduler() {
    this.lateCaptionOff?.()
    this.lateCaptionOff = null
    if (this.uiTimer) { clearInterval(this.uiTimer); this.uiTimer = null }
    this.scheduler?.stop()
    this.scheduler = null
    this.adapter?.destroy?.()
    this.adapter?.clear?.()
    this.adapter = null
    for (const off of this.listeners.splice(0)) off()
    // Cutting planId stops any in-flight pollPlanProgress loop on its next iteration.
    this.planId = null
    this.allUnits = []
    this.readyIds = new Set()
    this.planStatusValue = 'pending'
  }

  async restart() {
    this.teardownScheduler()
    this.videoId = videoId()
    this.lastVtt = ''
    this.overlay.update({
      status: 'idle', caption: '', glosses: [], activeGloss: null,
      progress: 0, coverage: null, unsupported: [], fallbackUnits: 0, detail: '',
    })
    this.video = await waitForVideo()
    if (this.video) this.media = createYouTubeMedia(this.video)
    await this.prepare()
  }

  /**
   * Optional convenience: save the captions actually used to a local file. Never required for
   * playback - everything stays in memory and is sent straight to the backend.
   */
  downloadCaptions() {
    if (!this.lastVtt) return
    const blob = new Blob([this.lastVtt], { type: 'text/vtt' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${this.videoId || 'captions'}.vtt`
    document.documentElement.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  }

  destroy() {
    this.destroyed = true
    this.teardownScheduler()
    this.bridge?.destroy()
    this.overlay?.destroy()
  }
}

export async function boot() {
  if (window.__signoraSession) return window.__signoraSession
  const session = new SignoraSession()
  window.__signoraSession = session
  try {
    await session.start()
  } catch (error) {
    warn('session failed to start', error)
  }
  return session
}
