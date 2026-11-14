/**
 * Orchestrator. Runs in the isolated content-script world on a YouTube watch page.
 *
 * Sequence: find the <video> -> check the backend -> get English captions (a manually picked file,
 * else the bundled lesson SRT for a known playlist video, else YouTube's own) -> convert to VTT ->
 * POST to the existing /api/v1/video-plans -> poll until ready -> hand the returned timed units
 * to the unmodified YouTubeSignScheduler, with the page's <video> adapted to its media contract
 * and an AvatarAdapter standing in for playback.
 *
 * Deliberately absent: any word/phrase matching. Resolving captions to glosses, multi-word
 * phrases, repeated occurrences, fingerspelling and unsupported-word reporting all already live
 * in backend/app/services/video_plan_service.py, and duplicating that here is exactly the
 * competing planner the task rules out.
 */

import {
  PLAYBACK_MODES, avatarRateFor, config, loadConfig, log, overrunPolicyFor, saveConfig, warn,
} from './config.js'
import { CaptionsUnavailableError, PageBridge, discoverCaptions } from './captions/discover.js'
import { timedTextToVtt } from './captions/convert.js'
import { startSubtitleSource } from './captions/bundled.js'
import { WATCHED_EVENTS, createYouTubeMedia, isYouTubeAdvertisement, videoEventToPlayerState } from './media/youtube-media.js'
import { MockAvatarAdapter } from './avatar/adapter.js'
import { UnityIframeAvatarAdapter } from './avatar/unity-iframe.js'
import { Overlay } from './overlay/overlay.js'
import {
  describeReadiness, diffNewlyReady, isPlanTerminal, progressSummary, summarizeIssues, toScheduleUnits,
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
    this.adShowing = false
    this.destroyed = false
    // A subtitle file the viewer picked, kept for this tab: it overrides bundled lesson SRTs and
    // YouTube captions for the video it was picked on, including after Retry or navigating back.
    this.manualSubtitle = null
    // Bumped whenever a newer caption choice supersedes an in-flight one.
    this.sourceGeneration = 0
  }

  // --- lifecycle ---------------------------------------------------------------------------

  async start() {
    await loadConfig()
    const settings = config()

    this.overlay = new Overlay({
      onRetry: () => this.restart(),
      onPickSubtitle: () => this.pickSubtitleFile(),
      onDownloadCaptions: () => this.downloadCaptions(),
      onChangeMode: (mode) => this.setPlaybackMode(mode),
    }).mount(settings.overlayExpanded)
    this.overlay.update({
      adapterName: settings.avatarAdapter,
      playbackMode: PLAYBACK_MODES[settings.playbackMode] ? settings.playbackMode : 'play-together',
    })

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

    const generation = ++this.sourceGeneration
    await startSubtitleSource({
      videoId: this.videoId,
      manual: this.manualSubtitle,
      loadBundled: (id) => callBackground('getBundledSubtitle', { videoId: id }),
      buildPlan: (text, options) => this.buildPlan(text, options),
      discover: () => this.discoverYouTubeCaptions(generation),
      report: (patch) => this.reportSubtitle(patch),
      isCurrent: () => !this.destroyed && generation === this.sourceGeneration,
    })
  }

  /** Overlay patch for the active caption source and any bundled-subtitle failure. */
  reportSubtitle({ source, subtitleError }) {
    const patch = {}
    if (source !== undefined) patch.subtitleSource = source
    if (subtitleError !== undefined) patch.subtitleError = subtitleError
    this.overlay.update(patch)
  }

  /** Normal caption discovery: capture the English captions YouTube's own player loads. */
  async discoverYouTubeCaptions(generation) {
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
    if (this.destroyed || generation !== this.sourceGeneration) return

    log('captions', captions.format, captions.cues.length, 'cues via', captions.via)
    this.overlay.update({
      subtitleSource: { kind: 'youtube' },
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
        subtitleSource: { kind: 'youtube' },
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
   *
   * `filename` tells the backend which parser to use (.srt or .vtt). Resolves to `{ ok: false,
   * error }` when the backend rejects the subtitle, so a bundled lesson can fall back.
   */
  async buildPlan(vtt, { filename = 'captions.vtt' } = {}) {
    const generation = this.sourceGeneration
    this.lastVtt = vtt
    this.overlay.update({ status: 'preparing-plan', detail: 'Sending captions to the Signora backend…' })
    let plan
    try {
      plan = await callBackground('createVideoPlan', {
        youtubeUrl: location.href.split('&')[0],
        vtt,
        filename,
      })
    } catch (error) {
      this.overlay.update({ status: 'plan-failed', detail: error.message })
      return { ok: false, error: error.message }
    }
    // A newer caption choice (e.g. a manual pick) arrived while this one was being posted.
    if (this.destroyed || generation !== this.sourceGeneration) return { ok: true }

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
    return { ok: true }
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
        // Units still composing will never arrive: stop waiting for them, so 'sync-pause' does
        // not hold the video at a boundary forever.
        this.scheduler?.updateUnits(toScheduleUnits(this.allUnits, this.planStatusValue, { settled: true }))
        return
      }
      if (this.destroyed || this.planId !== planId) return

      this.allUnits = plan.units
      this.planStatusValue = plan.status

      const { newlyReady, readyIds } = diffNewlyReady(plan.units, this.readyIds)
      this.readyIds = readyIds
      // The scheduler knows every unit from the start, each marked `motionPending` until it is
      // composed; this updates them in place as they become playable (or settle without motion).
      this.scheduler?.updateUnits(toScheduleUnits(plan.units, plan.status))
      if (newlyReady.length) {
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
    // service worker. It is given every unit at once, those still composing marked
    // `motionPending` - see pollPlanProgress(). Every other behaviour (play/pause/seek/rate/
    // overrun) is the scheduler's own logic.
    this.scheduler = new YouTubeSignScheduler({
      media: this.media,
      avatar: this.adapter,
      units: toScheduleUnits(plan.units, plan.status),
      loadMotion: (unit) => callBackground('getUnitMotion', unit.motionUrl),
      overrunPolicy: overrunPolicyFor(settings),
      prepareMotion: (motion, unit, policy) => {
        // Called as each sign starts, with the policy it plays under.
        this.adapter?.setPlaybackRate(avatarRateFor(policy, this.media.getPlaybackRate()))
        // 'sync-pause' holds the video for the sign, so the motion keeps its own recorded pace.
        return policy === 'sync-pause' ? motion : {
          ...motion,
          // This is a video-caption performance, not a live microphone queue.  Fit the entire
          // composed unit to its source cue so the avatar and spoken words progress together.
          playbackTiming: { targetDurationMs: Math.max(250, unit.endMs - unit.startMs) },
        }
      },
      onSync: (detail) => this.overlay.update({ detail }),
    })

    this.bindVideoEvents()
    this.scheduler.start()
    // Seed the scheduler with the player's current state so a video already playing is picked up.
    this.scheduler.setPlayerState(this.video.paused ? YT_STATE.PAUSED : YT_STATE.PLAYING)
    this.adapter.setPlaybackRate(avatarRateFor(this.scheduler.overrunPolicy, this.media.getPlaybackRate()))

    this.syncAdvertisementState()
    this.uiTimer = setInterval(() => {
      this.syncAdvertisementState()
      this.paintStatus()
    }, 250)
  }

  /** Freeze the lesson avatar whenever YouTube swaps its stream for an advertisement. */
  syncAdvertisementState() {
    const showing = isYouTubeAdvertisement(this.video)
    if (showing === this.adShowing) return
    this.adShowing = showing
    this.scheduler?.setExternalPause(showing)
    log(showing ? 'advertisement started — signing paused' : 'advertisement ended — signing resumed')
  }

  /**
   * Overlay toggle. The choice is saved immediately; a running scheduler adopts it at its next
   * unit boundary, so a sign in progress is never re-timed and a hold it took is still released.
   */
  async setPlaybackMode(mode) {
    if (!PLAYBACK_MODES[mode]) return
    const settings = await saveConfig({ playbackMode: mode })
    this.scheduler?.setOverrunPolicy(overrunPolicyFor(settings))
    this.overlay.update({ playbackMode: mode })
    log('playback mode', mode)
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
          // In 'sync-pause' the avatar keeps natural speed; the video resumes at the viewer's rate.
          this.adapter?.setPlaybackRate(avatarRateFor(this.scheduler?.overrunPolicy, rate))
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
    if (this.adShowing) {
      this.overlay.update({
        status: 'advertisement', caption: 'Advertisement — signing paused', glosses: [],
        activeGloss: null, unitStatus: null, fingerspelledWords: [],
      })
      return
    }
    const snapshot = this.adapter.snapshot?.() ?? {}
    const paused = Boolean(this.video?.paused)
    const autoPaused = Boolean(this.scheduler.autoPaused)
    const mediaMs = this.media.getCurrentTime() * 1000
    const readiness = describeReadiness(
      mediaMs, this.allUnits, this.readyIds, this.planStatusValue, config().lookaheadUnits,
    )

    let status
    if (autoPaused && this.scheduler.bufferingUnit) status = 'sync-buffering'
    else if (autoPaused) status = this.scheduler.overrunPolicy === 'sync-pause' ? 'sync-hold' : 'catch-up'
    else if (this.video?.ended) status = 'ended'
    else if (paused) status = 'paused'
    else if (snapshot.playing) status = 'signing'
    else if (readiness.state === 'buffering-current' || readiness.state === 'buffering-lookahead') {
      status = 'buffering-signs'
    } else status = 'ready'

    const patch = {
      status, progress: snapshot.progress ?? 0, rate: this.media.getPlaybackRate(),
      modePending: this.scheduler.pendingPolicy !== null,
    }
    const shown = readiness.unit ?? readiness.units?.[0] ?? null
    if (shown) {
      patch.caption = shown.text || ''
      patch.glosses = shown.glosses || []
      // Nothing is current yet when only the look-ahead is shown, so nothing is highlighted.
      patch.activeGloss = readiness.unit ? snapshot.activeGloss ?? null : null
      patch.unitStatus = shown.status
      patch.fingerspelledWords = shown.fingerspelledWords || []
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
        this.manualSubtitle = { videoId: this.videoId, name: file.name, text: vtt, filename: 'captions.vtt' }
        this.overlay.update({
          subtitleSource: { kind: 'manual', name: file.name },
          subtitleError: '',
          detail: `Using local file ${file.name}`,
        })
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
    this.sourceGeneration += 1
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
      status: 'idle', caption: '', glosses: [], activeGloss: null, unitStatus: null, fingerspelledWords: [],
      progress: 0, coverage: null, unsupported: [], fallbackUnits: 0, detail: '',
      subtitleSource: null, subtitleError: '',
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
