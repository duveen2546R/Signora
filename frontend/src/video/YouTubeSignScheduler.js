export const YT_STATE = { ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 }

export default class YouTubeSignScheduler {
  constructor({ media, avatar, units, loadMotion, onUnit, onSync, now = () => performance.now() }) {
    this.media = media
    this.avatar = avatar
    this.units = [...units].sort((a, b) => a.startMs - b.startMs)
    this.loadMotion = loadMotion
    this.onUnit = onUnit
    this.onSync = onSync
    this.now = now
    this.index = 0
    this.active = null
    this.autoPaused = false
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
    this.generation += 1
    this.avatar.resetToIdle?.()
  }

  setPlayerState(state) {
    this.playerState = state
    if (state === YT_STATE.PLAYING) this.avatar.resume?.()
    if ((state === YT_STATE.PAUSED && !this.autoPaused) || state === YT_STATE.BUFFERING) {
      this.avatar.pause?.()
    }
    if (state === YT_STATE.PAUSED && this.autoPaused) this.avatar.resume?.()
    if (state === YT_STATE.ENDED) this.avatar.resume?.()
    this.lastMediaMs = Number(this.media.getCurrentTime?.() ?? 0) * 1000
    this.lastWallMs = this.now()
  }

  _prefetch() {
    for (const unit of this.units.slice(this.index, this.index + 2)) {
      if (!unit.motionAvailable || this.cache.has(unit.id)) continue
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
      this.avatar.play(motion)
      this.active = unit
      this.onSync?.('Signing')
    } catch (error) {
      if (generation === this.generation) {
        this.index += 1
        this.onSync?.(`Motion unavailable: ${error.message}`)
      }
    }
  }

  _resync(mediaMs) {
    this.generation += 1
    this.active = null
    this.autoPaused = false
    this.avatar.resetToIdle?.()
    this.index = this.units.findIndex((unit) => unit.startMs >= mediaMs)
    if (this.index < 0) this.index = this.units.length
    this.onSync?.('Resynced after seek')
  }

  tick() {
    const wallMs = this.now()
    const mediaMs = Number(this.media.getCurrentTime?.() ?? 0) * 1000
    const current = this.units.find((unit) => mediaMs >= unit.startMs && mediaMs < unit.endMs) ?? null
    this.onUnit?.(current)

    if (this.lastMediaMs !== null && this.lastWallMs !== null) {
      const elapsedWall = wallMs - this.lastWallMs
      const expected = this.playerState === YT_STATE.PLAYING
        ? elapsedWall * Number(this.media.getPlaybackRate?.() ?? 1) : 0
      if (Math.abs((mediaMs - this.lastMediaMs) - expected) > 750) this._resync(mediaMs)
    }
    this.lastMediaMs = mediaMs
    this.lastWallMs = wallMs

    if (this.active && !this.avatar.isPlaying()) {
      this.active = null
      this.index += 1
      if (this.autoPaused) {
        this.autoPaused = false
        this.media.playVideo()
        this.onSync?.('Video resumed')
      } else {
        this.onSync?.('In sync')
      }
    }

    if (this.active && mediaMs >= this.active.endMs && this.avatar.isPlaying()
        && !this.autoPaused && this.playerState === YT_STATE.PLAYING) {
      this.autoPaused = true
      this.media.pauseVideo()
      this.avatar.resume?.()
      this.onSync?.('Video paused while the sign finishes')
    }

    while (!this.active && this.index < this.units.length && this.units[this.index].endMs <= mediaMs) {
      this.index += 1
    }
    const next = this.units[this.index]
    if (!this.active && next && mediaMs >= next.startMs && mediaMs < next.endMs) {
      if (next.motionAvailable) this._launch(next)
      else this.index += 1
    }
    this._prefetch()
  }
}
