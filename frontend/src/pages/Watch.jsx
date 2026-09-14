import { useCallback, useEffect, useRef, useState } from 'react'
import SignoraStage from '../components/SignoraStage'
import YouTubePlayer from '../components/YouTubePlayer'
import { api } from '../api/client'
import YouTubeSignScheduler from '../video/YouTubeSignScheduler'

const ERROR_MESSAGES = {
  2: 'The YouTube video ID is invalid.',
  5: 'This video cannot play in the HTML5 player.',
  100: 'This video is unavailable.',
  101: 'The owner does not allow this video to be embedded.',
  150: 'The owner does not allow this video to be embedded.',
}

export default function Watch() {
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [subtitle, setSubtitle] = useState(null)
  const [plan, setPlan] = useState(null)
  const [preparing, setPreparing] = useState(false)
  const [error, setError] = useState('')
  const [youtube, setYoutube] = useState(null)
  const [avatarReady, setAvatarReady] = useState(false)
  const [currentUnit, setCurrentUnit] = useState(null)
  const [syncStatus, setSyncStatus] = useState('Waiting for playback')
  const schedulerRef = useRef(null)

  const submit = async (event) => {
    event.preventDefault()
    if (!subtitle) return
    schedulerRef.current?.stop()
    setError('')
    setPlan(null)
    setYoutube(null)
    setPreparing(true)
    try {
      const created = await api.createVideoPlan(youtubeUrl, subtitle)
      setPlan(created)
      if (!['pending', 'processing'].includes(created.status)) setPreparing(false)
    } catch (requestError) {
      setError(requestError.message)
      setPreparing(false)
    }
  }

  useEffect(() => {
    if (!plan || !['pending', 'processing'].includes(plan.status)) {
      return undefined
    }
    let cancelled = false
    const poll = window.setInterval(async () => {
      try {
        const next = await api.videoPlan(plan.id)
        if (!cancelled) {
          setPlan(next)
          if (!['pending', 'processing'].includes(next.status)) setPreparing(false)
        }
      } catch (pollError) {
        if (!cancelled) {
          setError(pollError.message)
          setPreparing(false)
        }
      }
    }, 700)
    return () => {
      cancelled = true
      window.clearInterval(poll)
    }
  }, [plan])

  useEffect(() => {
    if (!plan || plan.status !== 'ready' || plan.stale || !youtube || !avatarReady || !window.signsure) {
      return undefined
    }
    const scheduler = new YouTubeSignScheduler({
      media: youtube,
      avatar: window.signsure,
      units: plan.units,
      loadMotion: (unit) => api.videoUnitMotion(unit.motionUrl),
      onUnit: setCurrentUnit,
      onSync: setSyncStatus,
    })
    schedulerRef.current = scheduler
    scheduler.start()
    return () => {
      scheduler.stop()
      if (schedulerRef.current === scheduler) schedulerRef.current = null
    }
  }, [plan, youtube, avatarReady])

  const onPlayerState = useCallback((state) => schedulerRef.current?.setPlayerState(state), [])
  const onPlayerReady = useCallback((player) => {
    const lastEnd = plan?.units.at(-1)?.endMs ?? 0
    const durationMs = Number(player.getDuration?.() ?? 0) * 1000
    if (durationMs && lastEnd > durationMs + 5_000) {
      setError('The subtitle timeline does not match this video. Choose the matching SRT or VTT file.')
      return
    }
    setYoutube(player)
  }, [plan])
  const onPlayerError = useCallback((code) => {
    const message = code instanceof Error ? code.message : ERROR_MESSAGES[code]
    setError(message || `YouTube player error ${code}.`)
  }, [])
  const onAvatarStatus = useCallback((status) => setAvatarReady(status.startsWith('calibrated:')), [])
  const onAvatarIdle = useCallback(() => schedulerRef.current?.tick(), [])

  const coverage = plan?.coverage
  const ready = plan?.status === 'ready'

  return (
    <section className="watch-page">
      <header className="watch-head">
        <p className="eyebrow">YouTube + ISL avatar</p>
        <h1>Watch with signs in parallel.</h1>
        <p>Use a YouTube link and its matching English SRT or VTT file. SignSure prepares complete signing units before playback.</p>
      </header>

      <form className="watch-setup" onSubmit={submit}>
        <label>
          <span>YouTube video URL</span>
          <input type="url" required value={youtubeUrl} onChange={(event) => setYoutubeUrl(event.target.value)} placeholder="https://www.youtube.com/watch?v=…" />
        </label>
        <label>
          <span>Matching subtitle file</span>
          <input type="file" required accept=".srt,.vtt,text/vtt,application/x-subrip" onChange={(event) => setSubtitle(event.target.files?.[0] ?? null)} />
        </label>
        <button className="button" type="submit" disabled={preparing}>{preparing ? 'Preparing signs…' : 'Prepare video'}</button>
      </form>

      {error && <p className="watch-alert" role="alert">{error}</p>}
      {plan?.status === 'failed' && <p className="watch-alert" role="alert">Preparation failed: {plan.error}</p>}
      {plan?.stale && <p className="watch-alert" role="alert">The sign library changed. Prepare this subtitle again before playing.</p>}

      {coverage && (
        <div className="watch-coverage" aria-label="Signing coverage">
          <div><strong>{coverage.percent}%</strong><span>playable coverage</span></div>
          <div><strong>{coverage.signedUnits}</strong><span>signed units</span></div>
          <div><strong>{coverage.fingerspelledUnits}</strong><span>with fingerspelling</span></div>
          <div><strong>{coverage.unsupportedUnits}</strong><span>skipped units</span></div>
        </div>
      )}

      {ready && !plan.stale && (
        <div className="watch-workspace">
          <div className="watch-video-panel">
            <YouTubePlayer videoId={plan.youtubeVideoId} onReady={onPlayerReady} onStateChange={onPlayerState} onError={onPlayerError} />
          </div>
          <div className="watch-avatar-panel">
            <SignoraStage onStatus={onAvatarStatus} onIdle={onAvatarIdle} />
          </div>
          <div className="watch-now" aria-live="polite">
            <div>
              <span className="eyebrow">Current caption</span>
              <p>{currentUnit?.text || 'Play the video to begin.'}</p>
            </div>
            <div>
              <span className="eyebrow">ISL plan</span>
              <p>{currentUnit?.glosses?.join(' · ') || '—'}</p>
              {currentUnit && <small>{currentUnit.status === 'ready' ? 'Reviewed pattern' : currentUnit.status === 'literal-preview' ? 'Literal preview' : 'No sign played for this unit'}</small>}
            </div>
            <div>
              <span className="eyebrow">Sync</span>
              <p>{syncStatus}</p>
            </div>
          </div>
          <p className="watch-note">The YouTube player is the timing master. If a complete sign runs past its caption, the video pauses and resumes automatically when the avatar finishes.</p>
        </div>
      )}
    </section>
  )
}
