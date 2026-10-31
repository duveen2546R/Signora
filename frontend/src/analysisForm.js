export const SOURCES = [
  { key: 'suit', title: 'MotionCapture FBX', accept: '.fbx', hint: 'The motion capture recording · up to 100 MB' },
  { key: 'video', title: 'Reference video', accept: '.mp4,.mov,.m4v', hint: 'The real person performing the action · up to 250 MB and 2 minutes' },
]

// Statistical equivalence: a second view of the same performance, and an optional noise recording
// (both phones unmoved; the performer holds still ~10 s, then moves slowly).
export const EQUIVALENCE_SOURCES = [
  { key: 'oblique', title: 'Side video (70–90°)', accept: '.mp4,.mov,.m4v', required: true, hint: 'The same performance filmed by a second phone 70–90° to the side (at least 30°) · up to 250 MB' },
  { key: 'noise_front', title: 'Noise recording — front (optional)', accept: '.mp4,.mov,.m4v', required: false, hint: 'Same front phone, not moved: hold still ~10 s, then move slowly' },
  { key: 'noise_oblique', title: 'Noise recording — oblique (optional)', accept: '.mp4,.mov,.m4v', required: false, hint: 'The same noise recording from the oblique phone' },
]

// The statistical-equivalence upload: one take filmed by two phones while the suit records it.
// Keys match createAnalysis: suit -> FBX, video -> front (reference) video, oblique -> side video.
export const TAKE_SOURCES = [
  { key: 'suit', title: 'Suit FBX', label: 'suit FBX', accept: '.fbx', limit: 100, hint: 'The Rokoko recording of this take · up to 100 MB' },
  { key: 'video', title: 'Front video', label: 'front video', accept: '.mp4,.mov,.m4v', limit: 250, hint: 'Phone facing the signer · up to 250 MB' },
  { key: 'oblique', title: 'Side video', label: 'side video', accept: '.mp4,.mov,.m4v', limit: 250, hint: 'Second phone, 70–90° to the side (at least 30°) · up to 250 MB' },
]

function checkFile(source, file) {
  const extension = `.${file.name.split('.').pop().toLowerCase()}`
  if (!source.accept.split(',').includes(extension)) throw new Error(`${source.title}: select a ${source.accept} file.`)
  if (!file.size || file.size > source.limit * 1024 * 1024) throw new Error(`${source.title}: use a nonempty file under ${source.limit} MB.`)
}

export function buildEquivalenceOptions({ files, action, confirmed, focal35mm = '' }) {
  for (const source of TAKE_SOURCES) {
    if (!files[source.key]) throw new Error(`Select the ${source.label} to continue.`)
    checkFile(source, files[source.key])
  }
  for (const key of ['noise_front', 'noise_oblique']) {
    if (files[key]) checkFile({ title: 'Noise recording', accept: '.mp4,.mov,.m4v', limit: 250 }, files[key])
  }
  if (!files.noise_front !== !files.noise_oblique) throw new Error('A noise recording needs both the front and the side video.')
  if (!confirmed) throw new Error('Confirm that both videos and the FBX are the same performance, recorded at the same time.')
  let focal = null
  if (focal35mm !== '') {
    focal = Number(focal35mm)
    if (!Number.isFinite(focal) || focal <= 8 || focal >= 300) throw new Error('Enter a 35 mm-equivalent focal length between 8 and 300 mm, or leave it blank.')
  }
  // The single-take pipeline finds the sign window and synchronises all three clocks itself, so
  // the legacy windows, calibration interval and manual timing stay at their neutral defaults.
  return {
    action: action.trim() || 'Statistical equivalence', pairing_confirmed: true, recording_relationship: 'same_performance',
    reference_view: 'front', tolerance_profile: 'statistical_equivalence', windows: {}, calibration_phase: [0, 0.15],
    synchronization: {}, ...(focal !== null ? { focal_35mm: focal } : {}),
  }
}

export function buildAnalysisOptions({ files, action, pairing, relationship = 'unknown', referenceView = 'automatic', toleranceProfile = 'replication', windows, calibration, verifiedTiming, timing, focal35mm = '' }) {
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
  let focal = null
  if (toleranceProfile === 'statistical_equivalence') {
    if (relationship !== 'same_performance') throw new Error('Statistical equivalence needs videos of the exact same performance as the FBX.')
    for (const source of EQUIVALENCE_SOURCES) {
      const file = files[source.key]
      if (!file) { if (source.required) throw new Error(`Select the ${source.title.toLowerCase()} to continue.`); continue }
      const extension = `.${file.name.split('.').pop().toLowerCase()}`
      if (!source.accept.split(',').includes(extension)) throw new Error(`${source.title}: select a ${source.accept} file.`)
      if (!file.size || file.size > 250 * 1024 * 1024) throw new Error(`${source.title}: use a nonempty file under 250 MB.`)
    }
    if (!files.noise_front !== !files.noise_oblique) throw new Error('A noise recording needs both the front and the oblique video.')
    if (focal35mm !== '') {
      focal = Number(focal35mm)
      if (!Number.isFinite(focal) || focal <= 8 || focal >= 300) throw new Error('Enter a 35 mm-equivalent focal length between 8 and 300 mm, or leave it blank.')
    }
  }
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
  return { action: action.trim() || 'Action comparison', pairing_confirmed: true, recording_relationship: relationship, reference_view: referenceView, tolerance_profile: toleranceProfile, windows: selectedWindows, calibration_phase: calibrationPhase, synchronization, ...(focal !== null ? { focal_35mm: focal } : {}) }
}
