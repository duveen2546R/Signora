export const SOURCES = [
  { key: 'suit', title: 'MotionCapture FBX', accept: '.fbx', hint: 'The motion capture recording · up to 100 MB' },
  { key: 'video', title: 'Reference video', accept: '.mp4,.mov,.m4v', hint: 'The real person performing the action · up to 250 MB and 2 minutes' },
]

export function buildAnalysisOptions({ files, action, pairing, relationship = 'unknown', referenceView = 'automatic', toleranceProfile = 'replication', windows, calibration, verifiedTiming, timing }) {
  for (const source of SOURCES) {
    const file = files[source.key]
    if (!file) throw new Error(`Select ${source.title.toLowerCase()} to continue.`)
    const extension = `.${file.name.split('.').pop().toLowerCase()}`
    if (!source.accept.split(',').includes(extension)) throw new Error(`${source.title}: select a ${source.accept} file.`)
    const limit = source.key === 'video' ? 250 : 100
    if (!file.size || file.size > limit * 1024 * 1024) throw new Error(`${source.title}: use a nonempty file under ${limit} MB.`)
  }
  if (!pairing) throw new Error('Confirm the recording relationship and that the video shows the real person.')
  if (!['same_performance', 'separate_repetitions', 'unknown'].includes(relationship)) throw new Error('Select the recording relationship.')
  if (verifiedTiming && relationship !== 'same_performance') throw new Error('Synchronized accuracy requires the exact same performance.')
  if (!['automatic', 'front'].includes(referenceView)) throw new Error('Select the reference camera view.')
  if (!['intelligibility', 'replication', 'statistical_equivalence'].includes(toleranceProfile)) throw new Error('Select the tolerance standard.')
  const selectedWindows = {}
  for (const source of SOURCES) {
    const entry = windows[source.key]
    if (entry.start === '' && entry.end === '') continue
    if (entry.start === '' || entry.end === '') throw new Error(`${source.title}: enter both action timestamps, or leave both blank.`)
    const start = Number(entry.start), end = Number(entry.end)
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) throw new Error(`${source.title}: the end must be later than the start.`)
    selectedWindows[source.key] = [start, end]
  }
  const calibrationPhase = [Number(calibration.start) / 100, Number(calibration.end) / 100]
  if (calibration.start === '' || calibration.end === '' || calibrationPhase.some((n) => !Number.isFinite(n)) || calibrationPhase[0] < 0 || calibrationPhase[1] > 1 || calibrationPhase[1] <= calibrationPhase[0]) throw new Error('Enter a neutral calibration interval within 0–100% of the selected action.')
  const synchronization = {}
  if (verifiedTiming) {
    for (const key of ['suit']) {
      const entry = timing[key]
      const video = Number(entry.video), fbx = Number(entry.fbx), rate = Number(entry.rate)
      if (entry.video === '' || entry.fbx === '' || !Number.isFinite(video) || !Number.isFinite(fbx) || video < 0 || fbx < 0 || !Number.isFinite(rate) || rate <= 0 || !entry.description.trim() || !entry.evidence.trim()) throw new Error('Verified timing requires a matching event, its timestamps, and clock evidence for each FBX.')
      if (rate !== 1 && !entry.rateEvidence.trim()) throw new Error('Explain the documented playback-rate correction for each changed clock.')
      synchronization[key] = {
        clock_verified: true, clock_evidence: entry.evidence,
        event: { reviewed: true, description: entry.description, video_seconds: video, fbx_seconds: fbx },
        video_seconds_per_fbx_second: rate, rate_evidence: entry.rateEvidence,
      }
    }
  }
  return { action: action.trim() || 'Action comparison', pairing_confirmed: true, recording_relationship: relationship, reference_view: referenceView, tolerance_profile: toleranceProfile, windows: selectedWindows, calibration_phase: calibrationPhase, synchronization }
}
