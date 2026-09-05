export const MIN_EDGE_SECONDS = 0.12
export const MIN_SIGN_SECONDS = 0.30

export async function inspectCaptureDuration(file) {
  const text = await file.text()
  const lines = text.split(/\r?\n/).filter((line) => line.trim())
  if (lines.length < 2 || lines[0].split(',')[0].trim() !== 'Timestamp') {
    throw new Error('Expected a Rokoko CSV whose first column is Timestamp.')
  }

  const timestamps = lines.slice(1).map((line) => Number(line.split(',')[0]))
  if (timestamps.some((value) => !Number.isFinite(value))) {
    throw new Error('The CSV contains an invalid Timestamp value.')
  }
  if (timestamps.length > 1 && timestamps.some((value, index) => index > 0 && value <= timestamps[index - 1])) {
    throw new Error('CSV timestamps must increase on every row.')
  }

  const first = timestamps[0]
  const intervals = timestamps.slice(1).map((value, index) => value - timestamps[index])
  intervals.sort((left, right) => left - right)
  const middle = Math.floor(intervals.length / 2)
  const step = intervals.length === 0 ? 0 : intervals.length % 2
    ? intervals[middle]
    : (intervals[middle - 1] + intervals[middle]) / 2
  return (timestamps.at(-1) - first + step) / 1000
}

export function validatePhaseDraft({ duration, signStart, signEnd, track }) {
  const start = Number(signStart)
  const end = Number(signEnd)
  if (signStart === '' || signEnd === '' || !Number.isFinite(start) || !Number.isFinite(end)) {
    return 'Enter both sign-start and sign-end times.'
  }
  if (start < 0 || end <= start || end > duration + 1e-6) {
    return `Use 0 ≤ start < end ≤ ${duration.toFixed(3)} seconds.`
  }
  if (
    start < MIN_EDGE_SECONDS
    || duration - end < MIN_EDGE_SECONDS
    || end - start < MIN_SIGN_SECONDS
  ) {
    return 'Include at least 0.120s of Start, 0.300s of Sign, and 0.120s of End motion.'
  }
  if (track?.timestampsSeconds) {
    const times = track.timestampsSeconds
    for (const boundary of [start, end]) {
      const nearest = times[nearestCaptureFrame(times, boundary)]
      if (Math.abs(nearest - boundary) > 0.00051) return `Choose a CSV Timestamp. Nearest frame: ${nearest.toFixed(6)}s.`
    }
    if (track.csvPhaseBounds && (Math.abs(start - track.csvPhaseBounds.signStartSeconds) > 0.00051 || Math.abs(end - track.csvPhaseBounds.signEndSeconds) > 0.00051)) {
      return 'These timestamps conflict with the CSV Phase column. Use its boundaries or correct the CSV and upload a new take.'
    }
  }
  return null
}

export function phaseDurations(draft) {
  if (validatePhaseDraft(draft)) return null
  const start = Number(draft.signStart)
  const end = Number(draft.signEnd)
  return { start, sign: end - start, end: draft.duration - end }
}

export function captureTimes(track) {
  return track.timestampsSeconds ?? Array.from({ length: track.frameCount }, (_, index) => index / track.fps)
}

export function nearestCaptureFrame(times, seconds) {
  let low = 0
  let high = times.length - 1
  while (low < high) {
    const middle = Math.floor((low + high) / 2)
    if (times[middle] < seconds) low = middle + 1
    else high = middle
  }
  return low > 0 && Math.abs(times[low - 1] - seconds) < Math.abs(times[low] - seconds) ? low - 1 : low
}

export function captureFrameAt(times, seconds) {
  const nearest = nearestCaptureFrame(times, seconds)
  return times[nearest] > seconds ? Math.max(0, nearest - 1) : nearest
}
