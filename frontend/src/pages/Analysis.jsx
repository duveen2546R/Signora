import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { SOURCES, buildAnalysisOptions } from '../analysisForm'


const STAGES = { queued: 'Waiting for the comparison to start…', inspecting: 'Checking files and recording clocks…', extracting: 'Tracking the joints in your video…', scoring: 'Comparing motion and preparing the report…' }
const INITIAL_WINDOWS = { suit: { start: '', end: '' }, non_suit: { start: '', end: '' }, video: { start: '', end: '' } }
const INITIAL_TIMING = Object.fromEntries(['suit', 'non_suit'].map((key) => [key, { description: '', video: '', fbx: '', rate: '1', evidence: '', rateEvidence: '' }]))
const observedDecision = (value) => ({ EQUIVALENT: 'Observed tolerance satisfied', 'NOT EQUIVALENT': 'Observed tolerance exceeded' }[value] ?? value)
const format = (value) => Number.isFinite(value) ? value.toFixed(3) : '—'


export function Result({ job }) {
  const summary = job.summary
  const primaryMode = summary.primary_analysis ?? (summary.analyses?.synchronized?.status === 'descriptive' ? 'synchronized' : 'phase_normalized')
  const analysis = summary.analyses?.[primaryMode] ?? { status: 'indeterminate', reason: 'No position analysis is available in this report.' }
  const available = analysis.status === 'descriptive'
  const certificates = Object.entries(analysis.comparison?.equivalence ?? {}).filter(([, certificate]) => certificate?.domains)
  const domains = certificates[0]?.[1].domains ?? {}
  const historical = summary.assessment_kind !== 'observed_tolerance'
  const similarity = summary.comparison_kind === 'movement_similarity' || job.recordingRelationshipCorrection === 'separate_repetitions'
  const artifacts = summary.artifacts ?? {}
  const figures = Array.isArray(artifacts.figures) ? artifacts.figures : []

  const trajectoriesPlot = artifacts.trajectories_plot
    ?? figures.find((f) => f.includes('synchronized_trajectories'))
    ?? figures.find((f) => f.includes('phase_normalized_trajectories'))
    ?? figures.find((f) => f.includes('trajectories'))

  const anglesPlot = artifacts.angles_plot
    ?? figures.find((f) => f.includes('synchronized_angles') && !f.includes('errors'))
    ?? figures.find((f) => f.includes('phase_normalized_angles') && !f.includes('errors'))
    ?? figures.find((f) => (f.endsWith('angles.png') || f.endsWith('angles.svg')) && !f.includes('errors'))

  const ftostPlot = artifacts.ftost_plot

  return (
    <section className="analysis__results" aria-labelledby="results-heading">
      <div className="panel__head"><div><p className="analysis__eyebrow">Your comparison</p><h2 id="results-heading">Analysis Results</h2></div><span className="status">Report generated</span></div>
      <p>{summary.performance_id}</p>
      {summary.message ? (
        <div
          className="analysis__notice"
          style={{
            backgroundColor: summary.equivalence_verdict === 'PASS' ? '#e6ffe6' : '#fff4e5',
            borderColor: summary.equivalence_verdict === 'PASS' ? '#4CAF50' : '#ff9800',
            color: summary.equivalence_verdict === 'PASS' ? '#1b5e20' : '#b74700',
            marginBottom: '2rem'
          }}
        >
          <strong style={{ fontSize: '1.05rem', display: 'block', marginBottom: '0.25rem' }}>{summary.message}</strong>
          <p style={{ margin: 0 }}>
            {summary.message_detail ||
              (summary.equivalence_verdict === 'PASS'
                ? 'The continuous 3D biometric curves fell strictly within the mathematical acceptance boundaries.'
                : 'Observed continuous joint curves exceeded the statistical equivalence margin.')}
          </p>
        </div>
      ) : (
        <p className="analysis__notice"><strong>Statistical equivalence not established.</strong> This report measures observable projected movement. Both tolerance profiles are exploratory; measurement uncertainty and acceptance margins have not been independently validated.</p>
      )}

      {/* Visual Graphs: 2D Trajectories, Projected Elbow Angles, and fTOST */}
      {(trajectoriesPlot || anglesPlot || ftostPlot) && (
        <div className="analysis__graphs" style={{ margin: '2rem 0' }}>
          <div className="panel__head" style={{ marginBottom: '1.25rem' }}>
            <div>
              <p className="analysis__eyebrow" style={{ marginBottom: '4px' }}>Motion Verification</p>
              <h3 style={{ fontSize: '1.35rem', fontWeight: 600 }}>Biometric Trajectory & Joint Angle Curves</h3>
            </div>
          </div>

          {trajectoriesPlot && (
            <figure className="analysis__figure" style={{ border: '1px solid var(--rule-on-light, #e2e8f0)', marginBottom: '2rem', padding: '1.25rem', background: '#fff', borderRadius: '16px' }}>
              <img
                src={api.analysisFile(job.jobId, trajectoriesPlot)}
                alt="Figure 4.5: Two-dimensional wrist and elbow trajectories from the reference video and MotionCapture FBX"
                style={{ width: '100%', height: 'auto', display: 'block', borderRadius: '8px' }}
              />
              <figcaption style={{ marginTop: '0.85rem', fontWeight: 500, color: 'var(--charcoal, #1e293b)', lineHeight: 1.5 }}>
                <strong>FIGURE 4.5:</strong> Two-dimensional wrist and elbow trajectories from the reference video and MotionCapture FBX.
              </figcaption>
            </figure>
          )}

          {anglesPlot && (
            <figure className="analysis__figure" style={{ border: '1px solid var(--rule-on-light, #e2e8f0)', marginBottom: '2rem', padding: '1.25rem', background: '#fff', borderRadius: '16px' }}>
              <img
                src={api.analysisFile(job.jobId, anglesPlot)}
                alt="Figure 4.6: Projected left and right elbow angles over reference-video time for the video and MotionCapture FBX"
                style={{ width: '100%', height: 'auto', display: 'block', borderRadius: '8px' }}
              />
              <figcaption style={{ marginTop: '0.85rem', fontWeight: 500, color: 'var(--charcoal, #1e293b)', lineHeight: 1.5 }}>
                <strong>FIGURE 4.6:</strong> Projected left and right elbow angles over reference-video time for the video and MotionCapture FBX.
              </figcaption>
            </figure>
          )}

          {ftostPlot && (
            <figure className="analysis__figure" style={{ border: '1px solid var(--rule-on-light, #e2e8f0)', marginBottom: '2rem', padding: '1.25rem', background: '#fff', borderRadius: '16px' }}>
              <img
                src={api.analysisFile(job.jobId, ftostPlot)}
                alt={`Figure 4.7: Statistical Equivalence (fTOST) for ${summary.performance_id || 'the action'}`}
                style={{ width: '100%', height: 'auto', display: 'block', borderRadius: '8px' }}
              />
              <figcaption style={{ marginTop: '0.85rem', fontWeight: 500, color: 'var(--charcoal, #1e293b)', lineHeight: 1.5 }}>
                <strong>FIGURE 4.7:</strong> Statistical Equivalence (fTOST) for {summary.performance_id || 'the action'} with SPM1d continuous tolerance bounds.
              </figcaption>
            </figure>
          )}
        </div>
      )}
      {!summary.message && historical && <p className="hint">Historical report: earlier scores and coverage rules are retained. Earlier equivalence labels describe observed thresholds only. Run a new comparison for native-clock coverage checks.</p>}
      {!summary.message && <p className="hint">Alignment: {primaryMode === 'synchronized' ? 'Declared or estimated synchronized timing' : 'Phase-normalized movement'}. Camera: {analysis.reference_view === 'front' ? 'Front view — declared reference orientation' : 'Automatic torso fit'}.</p>}
      {!summary.message && analysis.reference_view === 'front' && <p className="analysis__notice">The FBX is projected into an upright front view using its shoulders and world up. Review the overlay to confirm this matches the reference camera.</p>}
      {!summary.message && analysis.calibration_sensitivity?.unresolved && <p className="analysis__notice">Camera orientation remains ambiguous. Review the projected overlay before interpreting the verdict.</p>}

      {summary.artifacts?.comparison_overlay && <details className="analysis__advanced">
        <summary>Review video and projected FBX orientation</summary>
        <p className="hint">Video landmarks and the projected FBX at five sample times. Check shoulder direction, upright posture, and arm placement before interpreting the scores.</p>
        <img src={api.analysisFile(job.jobId, summary.artifacts.comparison_overlay)} alt="Video landmarks and projected FBX skeletons at five sample times" style={{ width: '100%', height: 'auto' }} />
      </details>}

      {available && !summary.message ? <>
        <h3>Observed Movement Assessment</h3>

        {/* Primary Statistical Overview: Functional Equivalence */}
        {certificates.length > 0 && (
          <div className="analysis__notice" style={{ marginTop: '1rem', marginBottom: '2rem', backgroundColor: 'inherit', padding: 0, border: 'none' }}>
            <p style={{ marginBottom: '1rem' }}>
              <strong>Observed tolerance checks:</strong> Each domain requires complete measurements of all required sides and joints over at least 80% of assessed time. Replication uses the maximum assessed deviation; the wider legacy profile uses a time-weighted P95. Passing these checks does not establish statistical equivalence or sign comprehension.
            </p>
            <div className="analysis__table-wrap">
              <table className="jobs" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid #ccc' }}>
                    <th style={{ padding: '0.75rem 0.5rem' }}>Measured domain</th>
                    <th style={{ padding: '0.75rem 0.5rem' }}>Exploratory limit</th>
                    {certificates.map(([label, certificate]) => <th key={label} style={{ padding: '0.75rem 0.5rem', textAlign: 'center' }}>{certificate.label ?? label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(domains).map(([key, suitDomain]) => {
                    const formatDeviation = format;
                    const renderCell = (label, dom = { status: 'INCONCLUSIVE' }) => (
                      <td key={label} style={{ padding: '0.75rem 0.5rem', textAlign: 'center', backgroundColor: dom.status === 'PASS' ? 'rgba(74, 222, 128, 0.15)' : (dom.status === 'FAIL' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(253, 224, 71, 0.15)') }}>
                        <strong>{dom.status === 'PASS' ? 'Observed threshold satisfied' : dom.status === 'FAIL' ? 'Observed threshold exceeded' : dom.status}</strong><br/>
                        <small>{formatDeviation(dom.tested_deviation ?? dom.max_deviation)}{dom.statistic === 'p95' ? ' (95th pct.)' : ''}</small><br /><small>Coverage: {Number.isFinite(dom.valid_fraction) ? `${(dom.valid_fraction * 100).toFixed(1)}%` : 'unavailable'}</small>
                      </td>
                    );
                    return (
                      <tr key={key} style={{ borderBottom: '1px solid #eee' }}>
                        <td style={{ padding: '0.75rem 0.5rem' }}><strong>{suitDomain.domain}</strong></td>
                        <td style={{ padding: '0.75rem 0.5rem' }}>{suitDomain.margin}</td>
                        {certificates.map(([label, certificate]) => renderCell(label, certificate.domains[key]))}
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr style={{ backgroundColor: '#f1f5f9', borderTop: '2px solid #ccc' }}>
                    <td colSpan={2} style={{ padding: '1rem 0.5rem', fontWeight: 'bold', textAlign: 'right', color: '#1e293b' }}>Observed assessment:</td>
                    {certificates.map(([label, certificate]) => <td key={label} style={{ padding: '1rem 0.5rem', textAlign: 'center', fontWeight: 'bold', color: certificate.decision === 'OBSERVED TOLERANCE SATISFIED' ? '#16a34a' : '#dc2626' }}>
                      {observedDecision(certificate.decision)}
                    </td>)}
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        )}

        {analysis.comparison?.equivalence?.error && analysis.comparison.equivalence.error !== 'statistical_equivalence' && <p className="error" role="status">Domain evaluation unavailable: {analysis.comparison.equivalence.error}</p>}
        {certificates.length === 0 && !analysis.comparison?.equivalence?.error && <p role="status">This report has no domain certificates. Run a new comparison to generate them.</p>}
      </> : !summary.message ? <p className="error" role="status">No shape scores were produced: {analysis.reason}</p> : null}

      {!summary.message && certificates.map(([label, certificate]) => <details className="analysis__advanced" key={label}>
        <summary>{certificate.label ?? label}: profiles, coverage and camera sensitivity</summary>
        {Object.entries(certificate.profile_sensitivity ?? {}).map(([profile, assessment]) => <div key={profile}>
          <h4>{profile === 'replication' ? 'Replication profile — maximum' : 'Wider legacy profile — time-weighted P95'}</h4>
          <p>{observedDecision(assessment.decision)}</p>
          <div className="analysis__table-wrap"><table className="jobs"><thead><tr><th>Domain</th><th>Exploratory limit</th><th>Observed deviation</th><th>Time coverage</th></tr></thead><tbody>
            {Object.entries(assessment.domains ?? {}).map(([key, domain]) => <tr key={key}><td>{domain.domain}</td><td>{format(domain.margin)}</td><td>{format(domain.tested_deviation)}</td><td>{Number.isFinite(domain.valid_fraction) ? `${(domain.valid_fraction * 100).toFixed(1)}%` : 'Unavailable'}</td></tr>)}
          </tbody></table></div>
        </div>)}
        <div className="analysis__table-wrap"><table className="jobs"><caption>Complete sample coverage by joint and hand</caption><thead><tr><th>Measurement</th><th>Coverage</th></tr></thead><tbody>
          {Object.entries(certificate.required_joint_coverage ?? {}).map(([name, fraction]) => <tr key={name}><td>{name.replaceAll('_', ' ')}</td><td>{(fraction * 100).toFixed(1)}%</td></tr>)}
          {Object.entries(certificate.hand_coverage ?? {}).map(([name, fraction]) => <tr key={name}><td>{name} hand — all finger points</td><td>{(fraction * 100).toFixed(1)}%</td></tr>)}
        </tbody></table></div>
        {certificate.camera_sensitivity && <><p>{certificate.camera_sensitivity.interpretation}</p><div className="analysis__table-wrap"><table className="jobs"><caption>Deviation ranges across admitted camera fits</caption><thead><tr><th>Domain</th><th>Range</th></tr></thead><tbody>
          {Object.entries(certificate.camera_sensitivity.domain_ranges ?? {}).map(([key, range]) => <tr key={key}><td>{certificate.domains[key]?.domain ?? key}</td><td>{range ? `${format(range[0])} – ${format(range[1])}` : 'Insufficient coverage'}</td></tr>)}
        </tbody></table></div></>}
      </details>)}
      {!summary.message && summary.alignment_sensitivity && <details className="analysis__advanced"><summary>Timing resolution sensitivity</summary><p>{summary.alignment_sensitivity.interpretation}</p><div className="analysis__table-wrap"><table className="jobs"><thead><tr><th>Event offset</th><th>Observed assessment</th></tr></thead><tbody>
        {(summary.alignment_sensitivity.scenarios ?? []).map((scenario) => <tr key={scenario.video_event_offset_s}><td>{format(scenario.video_event_offset_s * 1000)} ms</td><td>{scenario.reason ?? Object.values(scenario.certificates ?? {}).map((certificate) => `${certificate.label ?? 'Assessment'}: ${observedDecision(certificate.decision ?? 'Unavailable')}`).join('; ')}</td></tr>)}
      </tbody></table></div></details>}
      {summary.artifacts?.full_sequence_overlay && <details className="analysis__advanced"><summary>Review the full sequence of body and finger projections</summary><video controls preload="metadata" style={{ width: '100%' }} src={api.analysisFile(job.jobId, summary.artifacts.full_sequence_overlay)} /><a className="link" href={api.analysisFile(job.jobId, summary.artifacts.full_sequence_overlay, true)}>Download full-sequence overlay</a></details>}
      <div className="analysis__downloads">
        {[
          ['report.html', 'Download complete report'],
          ['summary.json', 'Download results'],
          ['manifest.json', 'Download annotations'],
          ...(trajectoriesPlot ? [[trajectoriesPlot, 'Download trajectories plot']] : []),
          ...(anglesPlot ? [[anglesPlot, 'Download elbow angles plot']] : []),
          ...(ftostPlot ? [[ftostPlot, 'Download fTOST equivalence plot']] : []),
          ...Object.values(summary.artifacts?.traces ?? {}).map((name) => [name, ({ synchronized_traces: 'Download timing traces', phase_normalized_traces: 'Download position traces', action_shape_traces: 'Download action angles', action_alignment: 'Download time alignment', finger_animation_traces: 'Download finger articulation' })[name.replace('.csv', '')] || 'Download traces']),
        ].map(([name, label]) => <a className="link" key={name} href={api.analysisFile(job.jobId, name, true)}>{label}</a>)}
      </div>
    </section>
  )
}

export default function Analysis() {
  const [searchParams, setSearchParams] = useSearchParams()
  const jobId = searchParams.get('job')
  const [files, setFiles] = useState({})
  const [videoUrl, setVideoUrl] = useState(null)
  const [windows, setWindows] = useState(INITIAL_WINDOWS)
  const [calibration, setCalibration] = useState({ start: '0', end: '15' })
  const [action, setAction] = useState('')
  const [pairing, setPairing] = useState(false)
  const [relationship, setRelationship] = useState('unknown')
  const [referenceView, setReferenceView] = useState('automatic')
  const [toleranceProfile, setToleranceProfile] = useState('replication')
  const [verifiedTiming, setVerifiedTiming] = useState(false)
  const [timing, setTiming] = useState(INITIAL_TIMING)
  const [readiness, setReadiness] = useState(null)
  const [job, setJob] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [pollError, setPollError] = useState(null)
  const [retry, setRetry] = useState(0)
  const busy = uploading || (job && !['done', 'failed'].includes(job.status))

  useEffect(() => {
    let active = true
    api.analysisReadiness().then((result) => { if (active) setReadiness(result) }).catch((e) => { if (active) setError(e.message) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    return () => { if (videoUrl) URL.revokeObjectURL(videoUrl) }
  }, [videoUrl])

  useEffect(() => {
    if (!jobId) return undefined
    const controller = new AbortController()
    let timer
    async function poll() {
      try {
        const result = await api.analysisStatus(jobId, controller.signal)
        if (controller.signal.aborted) return
        setJob(result)
        setPollError(null)
        if (!['done', 'failed'].includes(result.status)) timer = setTimeout(poll, 1500)
      } catch (e) {
        if (!controller.signal.aborted) setPollError(e.message)
      }
    }
    poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [jobId, retry])

  function updateWindow(key, field, value) {
    setWindows((current) => ({ ...current, [key]: { ...current[key], [field]: value } }))
  }
  function selectFile(key, file) {
    setFiles((current) => ({ ...current, [key]: file }))
    if (key === 'video') {
      setVideoUrl(file ? URL.createObjectURL(file) : null)
      if (file && (!action || action === 'Action comparison' || action === 'After')) {
        const base = file.name.replace(/\.[^/.]+$/, '').replace(/[_.-]/g, ' ').trim()
        if (base) setAction(base.charAt(0).toUpperCase() + base.slice(1))
      }
    }
    setError(null)
  }
  function updateTiming(key, field, value) {
    setTiming((current) => ({ ...current, [key]: { ...current[key], [field]: value } }))
  }
  async function submit(event) {
    event.preventDefault()
    setError(null)
    try {
      const options = buildAnalysisOptions({ files, action, pairing, relationship, referenceView, toleranceProfile, windows, calibration, verifiedTiming, timing })
      setUploading(true)
      const created = await api.createAnalysis(files, options)
      setJob(created)
      setSearchParams({ job: created.jobId })
    } catch (e) { setError(e.message) } finally { setUploading(false) }
  }

  return (
    <section className="analysis">
      <header className="page-masthead"><p>04 / Analysis</p><h1>Compare the<br />movement.</h1><span>Understand the motion.<br />Check the evidence.</span></header>
      <div className="analysis__body">
        <div className="analysis__intro"><h2>From recording to evidence.</h2><p>Upload a real-person video and a motion capture FBX recording. Matching performances support agreement checks; separate repetitions support movement similarity. Compare wrist and elbow paths, joint angles, and recording quality.</p></div>
        {readiness && !readiness.ready && <p className="error" role="alert">{readiness.message}</p>}
        <form onSubmit={submit}>
          <fieldset disabled={!!busy} className="analysis__form"><legend className="analysis__eyebrow">01 · Select the sources</legend>
            <label className="field">Comparison name<input value={action} onChange={(e) => setAction(e.target.value)} maxLength={120} placeholder="For example: ACTION — take 01" /></label>
            <label className="field">How were these recordings made?<select value={relationship} onChange={(e) => { setRelationship(e.target.value); setPairing(false); setVerifiedTiming(false) }}><option value="unknown">I’m not sure — movement similarity only</option><option value="separate_repetitions">Separate repetitions of the same action — movement similarity</option><option value="same_performance">One simultaneous performance — agreement comparison</option></select></label>
            <label className="field">Reference video camera view<select value={referenceView} onChange={(e) => setReferenceView(e.target.value)}><option value="automatic">Automatic — estimate camera orientation</option><option value="front">Front view — performer faces the camera</option></select></label>
            <label className="field">Tolerance standard<select value={toleranceProfile} onChange={(e) => setToleranceProfile(e.target.value)}><option value="intelligibility">Wider legacy profile — exploratory P95</option><option value="replication">Replication profile — exploratory maximum</option><option value="statistical_equivalence">Statistical Equivalence — SPM1d + fTOST</option></select></label>
            <p className="hint">For a front-facing video, choose Front view. The FBX may face any direction in its viewer; comparison uses the anatomical shoulders to align its projection.</p>
            {relationship !== 'same_performance' && <p className="analysis__notice">Separate repetitions can differ in hand paths, speed, and body position even with perfect capture. These uploads cannot establish which capture method is more accurate. For that, each FBX needs a video of its exact performance.</p>}
            <div className="analysis__uploads">{SOURCES.map((source, index) => <div className="analysis__upload" key={source.key}>
              <span className="analysis__number">0{index + 1}</span><h3>{source.title}</h3><p className="hint">{source.hint}</p>
              <label className="field">Select {source.title.toLowerCase()}<input type="file" accept={source.accept} onChange={(e) => selectFile(source.key, e.target.files?.[0] ?? null)} /></label>
              {files[source.key] && <p className="analysis__filename">{files[source.key].name} · {(files[source.key].size / 1024 / 1024).toFixed(1)} MB</p>}
              <div className="analysis__times"><label className="field">Action start (s)<input type="number" min="0" step="0.001" value={windows[source.key].start} onChange={(e) => updateWindow(source.key, 'start', e.target.value)} placeholder="Full clip" /></label><label className="field">Action end (s)<input type="number" min="0" step="0.001" value={windows[source.key].end} onChange={(e) => updateWindow(source.key, 'end', e.target.value)} placeholder="Full clip" /></label></div>
            </div>)}</div>
            <p className="hint">Leave both timestamps blank to compare the full clip, or trim each source to the same action. The video may be at most two minutes long.</p>
            {videoUrl && <div className="analysis__preview"><video controls src={videoUrl} preload="metadata" aria-label="Reference video preview" /><p className="hint">Preview the video to choose its action boundaries and a stable neutral calibration interval.</p></div>}
            <details className="analysis__advanced"><summary>Calibration and verified timing</summary>
              <h3>Neutral calibration interval</h3><p className="hint">A stable torso interval as a percentage of the selected action. The initial 0–15% is a starting point; review it against your recording.</p>
              <div className="analysis__times"><label className="field">Start (%)<input type="number" min="0" max="100" step="0.1" value={calibration.start} onChange={(e) => setCalibration((c) => ({ ...c, start: e.target.value }))} /></label><label className="field">End (%)<input type="number" min="0" max="100" step="0.1" value={calibration.end} onChange={(e) => setCalibration((c) => ({ ...c, end: e.target.value }))} /></label></div>
              <label className="analysis__check"><input type="checkbox" disabled={relationship !== 'same_performance'} checked={verifiedTiming} onChange={(e) => setVerifiedTiming(e.target.checked)} /><span>I have verified the source clocks and matching synchronization events.</span></label>
              <p className="hint">Synchronization requires one simultaneous performance. Leave this unchecked if recording speed is unknown; shape scores remain available.</p>
              {verifiedTiming && ['suit'].map((key) => <div className="analysis__timing" key={key}><h3>MotionCapture FBX synchronization</h3>
                <label className="field">Matching event description<input value={timing[key].description} onChange={(e) => updateTiming(key, 'description', e.target.value)} placeholder="For example: first visible movement" /></label>
                <div className="analysis__times"><label className="field">Event in video (s)<input type="number" min="0" step="0.001" value={timing[key].video} onChange={(e) => updateTiming(key, 'video', e.target.value)} /></label><label className="field">Event in FBX (s)<input type="number" min="0" step="0.001" value={timing[key].fbx} onChange={(e) => updateTiming(key, 'fbx', e.target.value)} /></label></div>
                <label className="field">How were the clocks verified?<input value={timing[key].evidence} onChange={(e) => updateTiming(key, 'evidence', e.target.value)} /></label>
                <label className="field">Video seconds per FBX second<input type="number" min="0.001" step="0.001" value={timing[key].rate} onChange={(e) => updateTiming(key, 'rate', e.target.value)} /></label>
                {Number(timing[key].rate) !== 1 && <label className="field">Evidence for the playback-rate change<input value={timing[key].rateEvidence} onChange={(e) => updateTiming(key, 'rateEvidence', e.target.value)} /></label>}
              </div>)}
            </details>
            <label className="analysis__check"><input type="checkbox" checked={pairing} onChange={(e) => setPairing(e.target.checked)} /><span>I confirm the recording relationship selected above. The video shows the real person performing the action and is not rendered from either FBX.</span></label>
            {error && <p className="error" role="alert">{error}</p>}
            <div className="analysis__submit"><button className="button" type="submit" disabled={readiness && !readiness.ready}>{uploading ? 'Uploading recordings…' : 'Run comparison'}</button><p className="hint">Files and results are stored on this backend. Processing may take a few minutes.</p></div>
          </fieldset>
        </form>
        {jobId && <div className="analysis__progress" role="status" aria-live="polite">
          {pollError ? <><p className="error">Could not refresh the analysis: {pollError}</p><button className="button button--ghost" onClick={() => setRetry((r) => r + 1)}>Retry status</button></> : !job ? <p>Loading your comparison…</p> : job.status === 'failed' ? <p className="error">{job.error}</p> : job.status !== 'done' ? <><progress aria-label="Analysis in progress" /><p>{STAGES[job.status] ?? 'Processing your comparison…'}</p><p className="hint">You can return to this page using its current URL.</p></> : null}
        </div>}
        {job?.status === 'done' && <Result key={job.jobId} job={job} />}
      </div>
    </section>
  )
}
