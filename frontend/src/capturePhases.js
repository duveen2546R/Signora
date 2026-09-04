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

export function validatePhaseDraft({ duration, signStart, signEnd }) {
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
  return null
}

export function phaseDurations(draft) {
  if (validatePhaseDraft(draft)) return null
  const start = Number(draft.signStart)
  const end = Number(draft.signEnd)
  return { start, sign: end - start, end: draft.duration - end }
}
