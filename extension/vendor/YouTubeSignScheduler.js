export const YT_STATE = { ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 }

// 'continue': video and avatar run together. 'pause': pause only when a sign overruns its cue.
// 'sync-pause': pause the video at the exact start of every unit, wait for its motion if it is
// still composing, play the whole sign, and resume the video only when the avatar finishes.
export const OVERRUN_POLICIES = ['continue', 'pause', 'sync-pause']

// A unit with `motionPending: true` is still being composed: it is waited for, never skipped.
// In 'sync-pause' a pause that lands later than this past the unit's start is snapped back to it.
const SNAP_TOLERANCE_MS = 40

export default class YouTubeSignScheduler {
  constructor({ media, avatar, units, loadMotion, onUnit, onSync, now = () => performance.now(),
    overrunPolicy = 'pause', prepareMotion = (motion) => motion, maxHoldMs = 60000 }) {
    this.media = media
    this.avatar = avatar
    this.units = [...units].sort((a, b) => a.startMs - b.startMs)
    this.loadMotion = loadMotion
    this.onUnit = onUnit
    this.onSync = onSync
    this.now = now
    this.overrunPolicy = overrunPolicy
    this.prepareMotion = prepareMotion
    this.maxHoldMs = maxHoldMs
    this.pendingPolicy = null
    this.index = 0
    this.active = null
    this.autoPaused = false
    // YouTube advertisements reuse the lesson's <video> element but have an unrelated clock.
    // Preserve the lesson plan and freeze the exact avatar frame until content returns.
    this.externalPaused = false
    this.heldUnit = null
    this.holdStartedMs = null
    this.overriddenUnit = null
    this.boundaryTimer = null
    this.playerState = YT_STATE.CUED
    this.cache = new Map()
    this.lastMediaMs = null
    this.lastWallMs = null
    this.generation = 0
    this.timer = null
  }

  start() {
    if (this.timer === null) this.timer = setInterval(() => this.tick(), 100)
    this.tick()
  }

  stop() {
    if (this.timer !== null) clearInterval(this.timer)
    this.timer = null
    this._clearBoundaryTimer()
    this.generation += 1
    this.avatar.resetToIdle?.()
    // Never leave the video held by a pause the scheduler took.
    if (this.autoPaused) this._release()
  }

  /** Switch policy at the next unit boundary, so a sign in progress is never cut or re-timed. */
  setOverrunPolicy(policy) {
    if (!OVERRUN_POLICIES.includes(policy)) throw new Error(`unknown overrun policy: ${policy}`)
    this.pendingPolicy = policy
    if (!this.active) this._applyPendingPolicy()
  }

  /** Pause all lesson scheduling while YouTube is playing an advertisement. */
  setExternalPause(paused) {
    const next = Boolean(paused)
    if (this.externalPaused === next) return
    this.externalPaused = next
    this._clearBoundaryTimer()
    if (next) {
      this.avatar.pause?.()
      this.onSync?.('Advertisement playing — signing paused')
    } else {
      // Ad media time is not lesson media time; do not mistake the swap for a viewer seek.
      this.lastMediaMs = Number(this.media.getCurrentTime?.() ?? 0) * 1000
      this.lastWallMs = this.now()
      if (this.playerState === YT_STATE.PLAYING && !this.autoPaused) this.avatar.resume?.()
      this.onSync?.('Advertisement ended')
    }
  }

  /**
   * Merge fresh unit data (e.g. a unit whose motion just finished composing) into the schedule.
   * Known units are updated in place so `active`/`heldUnit` keep their identity; new ones are
   * inserted in start order without moving the unit the schedule is currently on.
   */
  updateUnits(units) {
    const current = this.units[this.index] ?? null
    const byId = new Map(this.units.map((unit) => [unit.id, unit]))
    for (const unit of units) {
      if (byId.has(unit.id)) Object.assign(byId.get(unit.id), unit)
      else this.units.push(unit)
    }
    this.units.sort((a, b) => a.startMs - b.startMs)
    if (current) this.index = this.units.indexOf(current)
  }

  /** The unit the video is held at while its motion is still being composed, if any. */
  get bufferingUnit() {
    return this.autoPaused && this.heldUnit && this.heldUnit !== this.active ? this.heldUnit : null
  }

  _applyPendingPolicy() {
    if (this.pendingPolicy === null) return
    this.overrunPolicy = this.pendingPolicy
    this.pendingPolicy = null
  }

  _hold(message, unit = this.active) {
    this.autoPaused = true
    this.heldUnit = unit
    this.holdStartedMs = this.now()
    this.media.pauseVideo()
    this.avatar.resume?.()
    this.onSync?.(message)
  }

  _release() {
    this.autoPaused = false
    this.holdStartedMs = null
    try {
      this.media.playVideo()
    } catch {
      // A player torn down during stop() cannot be resumed; there is nothing left to hold.
    }
  }

  setPlayerState(state) {
    // The viewer pressed play while the scheduler held the video: their choice wins, and the
    // held unit is not paused again.
    if (state === YT_STATE.PLAYING && this.autoPaused) {
      this.autoPaused = false
      this.holdStartedMs = null
      this.overriddenUnit = this.heldUnit
    }
    this.playerState = state
    if (this.externalPaused) {
      // YouTube emits normal player events while it swaps ad creatives. None of them should
      // restart the lesson avatar until the ad marker itself disappears.
      this.avatar.pause?.()
      this.lastMediaMs = Number(this.media.getCurrentTime?.() ?? 0) * 1000
      this.lastWallMs = this.now()
      return
    }
    if (state === YT_STATE.PLAYING) this.avatar.resume?.()
    if ((state === YT_STATE.PAUSED && !this.autoPaused)
        || (state === YT_STATE.BUFFERING && !this.autoPaused)) {
      this.avatar.pause?.()
    }
    if (state === YT_STATE.PAUSED && this.autoPaused) this.avatar.resume?.()
    if (state === YT_STATE.ENDED) this.avatar.resume?.()
    this.lastMediaMs = Number(this.media.getCurrentTime?.() ?? 0) * 1000
    this.lastWallMs = this.now()
  }

  _prefetch() {
    // The next two units that have motion; units still composing do not use up the look-ahead.
    for (const unit of this.units.slice(this.index).filter((u) => u.motionAvailable).slice(0, 2)) {
      if (this.cache.has(unit.id)) continue
      const promise = Promise.resolve(this.loadMotion(unit)).catch((error) => ({ loadError: error }))
      this.cache.set(unit.id, promise)
    }
  }

  async _launch(unit) {
    const generation = this.generation
    this.onSync?.('Preparing sign')
    try {
      if (!this.cache.has(unit.id)) this.cache.set(unit.id, Promise.resolve(this.loadMotion(unit)))
      const motion = await this.cache.get(unit.id)
      if (motion?.loadError) throw motion.loadError
      if (generation !== this.generation || this.active) return
      this.avatar.play(this.prepareMotion(motion, unit, this.overrunPolicy))
      this.active = unit
      this.onSync?.('Signing')
      if (this.overrunPolicy === 'sync-pause' && this.playerState === YT_STATE.PLAYING
          && this.heldUnit !== unit && this.overriddenUnit !== unit) {
        this._hold('Video paused while the avatar signs')
      }
    } catch (error) {
      if (generation === this.generation) {
        this.index += 1
        // A unit that cannot play must not keep the video held at its start.
        if (this.autoPaused && this.heldUnit === unit) this._release()
        if (this.heldUnit === unit) this.heldUnit = null
        this.onSync?.(`Motion unavailable: ${error.message}`)
      }
    }
  }

  /**
   * 'sync-pause' at a unit boundary: hold the video exactly at the unit's start (snapping back a
   * pause that landed late), then play the motion as soon as it is composed. A unit whose hold the
   * viewer overrode by pressing play is still signed if it becomes ready, but never held again.
   */
  _engageSync(unit, mediaMs) {
    if (this.heldUnit !== unit && this.overriddenUnit !== unit && this.playerState === YT_STATE.PLAYING) {
      this._hold(unit.motionAvailable ? 'Video paused while the avatar signs' : 'Buffering next sign…', unit)
      if (mediaMs - unit.startMs > SNAP_TOLERANCE_MS && this.media.seekTo) {
        this.media.seekTo(unit.startMs / 1000, true)
        this.lastMediaMs = unit.startMs
      }
    }
    if (unit.motionAvailable) this._launch(unit)
  }

  /** One 'sync-pause' scheduling step; `previousMediaMs` is null when this tick was a seek. */
  _syncStep(mediaMs, previousMediaMs) {
    if (this.active) return
    for (;;) {
      const unit = this.units[this.index]
      if (!unit) return
      const held = this.heldUnit === unit
      if (mediaMs < unit.startMs && !held) {
        this._armBoundary(unit, mediaMs)
        return
      }
      // Crossed by ordinary playback since the last tick, however short the unit: never skipped.
      const crossed = previousMediaMs !== null && unit.startMs > previousMediaMs
      const passed = unit.endMs <= mediaMs && !crossed && !held
      const settledWithoutMotion = !unit.motionAvailable && !unit.motionPending
      const abandoned = this.overriddenUnit === unit && unit.endMs <= mediaMs
      if (passed || settledWithoutMotion || abandoned) {
        if (held && this.autoPaused) this._release()
        if (held) this.heldUnit = null
        this.index += 1
        continue
      }
      this._engageSync(unit, mediaMs)
      return
    }
  }

  /** Wake exactly when media time reaches the next unit's start, instead of up to a tick late. */
  _armBoundary(unit, mediaMs) {
    this._clearBoundaryTimer()
    if (this.timer === null || this.playerState !== YT_STATE.PLAYING) return
    const rate = Number(this.media.getPlaybackRate?.() ?? 1) || 1
    const delay = (unit.startMs - mediaMs) / rate
    if (delay > 150) return
    this.boundaryTimer = setTimeout(() => {
      this.boundaryTimer = null
      this.tick()
    }, Math.max(0, delay))
  }

  _clearBoundaryTimer() {
    if (this.boundaryTimer !== null) clearTimeout(this.boundaryTimer)
    this.boundaryTimer = null
  }

  _resync(mediaMs) {
    this.generation += 1
    this.active = null
    this.heldUnit = null
    this.overriddenUnit = null
    this._clearBoundaryTimer()
    this.avatar.resetToIdle?.()
    // The motion the video was waiting for is gone; hand playback back instead of staying paused.
    if (this.autoPaused) this._release()
    this._applyPendingPolicy()
    this.index = this.units.findIndex((unit) => unit.startMs >= mediaMs)
    if (this.index < 0) this.index = this.units.length
    this.onSync?.('Resynced after seek')
  }

  tick() {
    const wallMs = this.now()
    const mediaMs = Number(this.media.getCurrentTime?.() ?? 0) * 1000
    if (this.externalPaused) {
      this.lastMediaMs = mediaMs
      this.lastWallMs = wallMs
      return
    }
    const current = this.units.find((unit) => mediaMs >= unit.startMs && mediaMs < unit.endMs) ?? null
    this.onUnit?.(current)

    let previousMediaMs = this.lastMediaMs
    if (this.lastMediaMs !== null && this.lastWallMs !== null) {
      const elapsedWall = wallMs - this.lastWallMs
      const expected = this.playerState === YT_STATE.PLAYING
        ? elapsedWall * Number(this.media.getPlaybackRate?.() ?? 1) : 0
      if (Math.abs((mediaMs - this.lastMediaMs) - expected) > 750) {
        this._resync(mediaMs)
        previousMediaMs = null
      }
    }
    this.lastMediaMs = mediaMs
    this.lastWallMs = wallMs

    if (this.active && this.autoPaused && this.holdStartedMs !== null
        && wallMs - this.holdStartedMs > this.maxHoldMs) {
      // An avatar that never reports completion must not keep the video paused forever.
      this.avatar.resetToIdle?.()
    }

    if (this.active && !this.avatar.isPlaying()) {
      this.active = null
      this.heldUnit = null
      this.index += 1
      if (this.autoPaused) {
        this._release()
        this.onSync?.('Video resumed')
      } else {
        this.onSync?.('In sync')
      }
    }
    if (!this.active) this._applyPendingPolicy()

    const canHold = this.active && this.avatar.isPlaying() && !this.autoPaused
      && this.playerState === YT_STATE.PLAYING && this.heldUnit !== this.active
    if (canHold && this.overrunPolicy === 'pause' && mediaMs >= this.active.endMs) {
      this._hold('Video paused while the sign finishes')
    } else if (canHold && this.overrunPolicy === 'sync-pause') {
      this._hold('Video paused while the avatar signs')
    }

    if (this.overrunPolicy === 'sync-pause') {
      this._syncStep(mediaMs, previousMediaMs)
      this._prefetch()
      return
    }

    while (!this.active && this.index < this.units.length && this.units[this.index].endMs <= mediaMs) {
      this.index += 1
    }
    const next = this.units[this.index]
    if (!this.active && next && mediaMs >= next.startMs && mediaMs < next.endMs) {
      if (next.motionAvailable) this._launch(next)
      else if (!next.motionPending) this.index += 1
    }
    this._prefetch()
  }
}
