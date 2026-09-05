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

/** Round an authored boundary onto the nearest captured CSV row. */
export function snapBoundary(track, seconds) {
  const value = Number(seconds)
  if (!track?.timestampsSeconds || !Number.isFinite(value)) return value
  const times = track.timestampsSeconds
  return times[nearestCaptureFrame(times, value)]
}

/**
 * The boundaries a draft will actually be saved with.
 *
 * Row timestamps are irregular and nobody authoring a sign knows them, so a typed or dragged
 * value is rounded to the nearest captured frame rather than refused. Callers submit these
 * values, so what is validated is what is stored.
 */
export function snapPhaseDraft({ signStart, signEnd, track }) {
  return { signStart: snapBoundary(track, signStart), signEnd: snapBoundary(track, signEnd) }
}

/**
 * The boundaries the editor should open on for a capture.
 *
 * A take's own saved boundaries win: once it has been reviewed, those are what it plays with, so
 * reopening the editor has to show them. The CSV Phase column is only a seed for a take nobody has
 * reviewed yet - reading it first makes every saved edit look as though it was discarded.
 */
export function initialPhaseDraft(raw) {
  return {
    signStart: raw?.signStartSeconds ?? raw?.csvPhaseBounds?.signStartSeconds ?? '',
    signEnd: raw?.signEndSeconds ?? raw?.csvPhaseBounds?.signEndSeconds ?? '',
  }
}

export function validatePhaseDraft({ duration, signStart, signEnd, track }) {
  if (signStart === '' || signEnd === '' || !Number.isFinite(Number(signStart)) || !Number.isFinite(Number(signEnd))) {
    return 'Enter both sign-start and sign-end times.'
  }
  // Validate the snapped values: rounding can move a boundary a few milliseconds either way, and
  // the limits below have to hold for the times that get saved, not for what was typed.
  const { signStart: start, signEnd: end } = snapPhaseDraft({ signStart, signEnd, track })
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
  return null
}

export function phaseDurations(draft) {
  if (validatePhaseDraft(draft)) return null
  const { signStart: start, signEnd: end } = snapPhaseDraft(draft)
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
