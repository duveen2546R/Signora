import { useEffect, useId, useMemo, useRef, useState } from 'react'

import { captureTimes, captureFrameAt, nearestCaptureFrame } from '../capturePhases'

const BODY = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24], [23, 25], [25, 27], [24, 26], [26, 28]]
const HAND = [1, 5, 9, 13, 17].flatMap((start) => [[0, start], [start, start + 1], [start + 1, start + 2], [start + 2, start + 3]])

function Skeleton({ track, index, axis, bounds }) {
  const { low, high } = bounds
  const scale = 200 / Math.max(high[axis] - low[axis], high[1] - low[1], 0.1)
  const project = (p) => [130 + (p[axis] - (low[axis] + high[axis]) / 2) * scale, 230 - (p[1] - low[1]) * scale]
  const lines = (points, edges, className) => edges.map(([a, b]) => {
    const [x1, y1] = project(points[a])
    const [x2, y2] = project(points[b])
    return <line key={`${a}-${b}`} x1={x1} y1={y1} x2={x2} y2={y2} className={className} />
  })
  const [cx, cy] = project(track.pose[index][0])
  return (
    <svg viewBox="0 0 260 260" role="img" aria-label={`${axis === 0 ? 'Front' : 'Side'} view of captured frame ${index + 1}`}>
      <text x="12" y="20">{axis === 0 ? 'Front' : 'Side'}</text>
      <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        {lines(track.pose[index], BODY)}
        <circle cx={cx} cy={cy} r="9" />
        {lines(track.leftHand[index], HAND, 'motion-editor__left')}
        {lines(track.rightHand[index], HAND, 'motion-editor__right')}
      </g>
    </svg>
  )
}

/** Shared upload/library annotation controls; preview never trims or blends the capture. */
export default function MotionPhaseEditor({ track, signStart, signEnd, onChange, disabled = false }) {
  const id = useId()
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [zoom, setZoom] = useState(1)
  const playhead = useRef(0)
  const times = useMemo(() => captureTimes(track), [track])
  const bounds = useMemo(() => {
    const low = [Infinity, Infinity, Infinity]
    const high = [-Infinity, -Infinity, -Infinity]
    for (const points of track.pose) for (const p of points) for (let k = 0; k < 3; k++) {
      low[k] = Math.min(low[k], p[k]); high[k] = Math.max(high[k], p[k])
    }
    return { low, high }
  }, [track])

  useEffect(() => {
    if (!playing || disabled) return undefined
    let request
    let last = performance.now()

    const tick = (now) => {
      if (!document.hidden) playhead.current += (now - last) / 1000
      last = now
      const duration = track.durationSeconds ?? track.frameCount / track.fps
      playhead.current %= duration
      setFrame(captureFrameAt(times, playhead.current))
      request = requestAnimationFrame(tick)
    }
    const visibility = () => { last = performance.now() }
    document.addEventListener('visibilitychange', visibility)
    request = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(request)
      document.removeEventListener('visibilitychange', visibility)
    }
  }, [playing, disabled, track, times])

  function seek(value) {
    setPlaying(false)
    setFrame(Math.max(0, Math.min(track.frameCount - 1, value)))
  }
  const time = times[frame]
  const phase = signStart === '' || signEnd === '' ? 'Unmarked' : time < Number(signStart) ? 'Start' : time < Number(signEnd) ? 'Sign' : 'End'
  return (
    <fieldset className="motion-editor" disabled={disabled}>
      <legend>Review captured movement</legend>
      <p className="hint">Keep the full sign and its holds. Times are seconds from the first CSV Timestamp; each slider step selects a captured CSV row.</p>
      {track.csvPhaseBounds && <p className="hint">CSV Phase boundaries: {track.csvPhaseBounds.signStartSeconds.toFixed(6)}s → {track.csvPhaseBounds.signEndSeconds.toFixed(6)}s. Inputs must match these values. To change them, correct the CSV Phase column and upload a new take.</p>}
      <div className="motion-editor__viewport">
        <div className="motion-editor__views" style={{ width: `${zoom * 100}%` }}>
          <Skeleton track={track} index={frame} axis={0} bounds={bounds} />
          <Skeleton track={track} index={frame} axis={2} bounds={bounds} />
        </div>
      </div>
      <label>Preview magnification
        <select value={zoom} onChange={(event) => setZoom(Number(event.target.value))}>
          <option value={1}>1×</option><option value={2}>2×</option><option value={3}>3×</option>
        </select>
      </label>
      <p className="mono">Frame {frame + 1}/{track.frameCount} · {time.toFixed(6)}s · {phase}</p>
      <label htmlFor={`${id}-frame`}>Playback position</label>
      <input id={`${id}-frame`} type="range" min="0" max={track.frameCount - 1} step="1" value={frame} onChange={(event) => seek(Number(event.target.value))} />
      <div className="phase-draft__actions">
        <button type="button" className="secondary" onClick={() => seek(frame - 1)} disabled={frame === 0}>Previous frame</button>
        <button type="button" onClick={() => { playhead.current = times[frame]; setPlaying(!playing) }}>{playing ? 'Pause' : 'Play capture'}</button>
        <button type="button" className="secondary" onClick={() => seek(frame + 1)} disabled={frame === track.frameCount - 1}>Next frame</button>
      </div>
      {[
        ['signStart', 'Start → Sign', signStart],
        ['signEnd', 'Sign → End', signEnd],
      ].map(([key, label, value]) => (
        <div className="motion-editor__boundary" key={key}>
          <label htmlFor={`${id}-${key}`}>{label} (seconds)</label>
          <input id={`${id}-${key}`} type="number" required min="0" max={times.at(-1)} step="any" value={value}
            onChange={(event) => onChange({ [key]: event.target.value })} />
          <input type="range" aria-label={`${label} boundary`} min="0" max={track.frameCount - 1} step="1" value={value === '' ? 0 : nearestCaptureFrame(times, Number(value))}
            onChange={(event) => onChange({ [key]: String(times[Number(event.target.value)]) })} />
          <button type="button" className="secondary" onClick={() => onChange({ [key]: String(time) })}>Use current frame</button>
        </div>
      ))}
    </fieldset>
  )
}
