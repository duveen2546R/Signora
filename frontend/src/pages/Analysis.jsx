import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { SOURCES, buildAnalysisOptions } from '../analysisForm'
import ActionShapeResult from '../components/ActionShapeResult'

const STAGES = { queued: 'Waiting for the comparison to start…', inspecting: 'Checking files and recording clocks…', extracting: 'Tracking the joints in your video…', scoring: 'Comparing motion and preparing the report…' }
const INITIAL_WINDOWS = { suit: { start: '', end: '' }, non_suit: { start: '', end: '' }, video: { start: '', end: '' } }
const INITIAL_TIMING = Object.fromEntries(['suit', 'non_suit'].map((key) => [key, { description: '', video: '', fbx: '', rate: '1', evidence: '', rateEvidence: '' }]))
const format = (value) => Number.isFinite(value) ? value.toFixed(3) : '—'
const formatRange = (bounds) => bounds?.map(format).join(' to ') ?? '—'

function Result({ job }) {
  const summary = job.summary
  const analysis = summary.analyses.phase_normalized
  const available = analysis.status === 'descriptive'
  const sensitivity = analysis.calibration_sensitivity
  const similarity = summary.comparison_kind === 'movement_similarity' || job.recordingRelationshipCorrection === 'separate_repetitions'
  const metricName = similarity ? 'difference' : 'error'
  const [showReport, setShowReport] = useState(false)
  return (
    <section className="analysis__results" aria-labelledby="results-heading">
      <div className="panel__head"><div><p className="analysis__eyebrow">Your comparison</p><h2 id="results-heading">Analysis Results</h2></div><span className="status">Report generated</span></div>
      <p>{summary.performance_id}</p>

      {/* Group verbose warnings into a collapsible block */}
      <details className="analysis__advanced" style={{ marginBottom: '1.5rem' }}>
        <summary>Diagnostic Warnings & Assumptions</summary>
        <div style={{ marginTop: '1rem' }}>
          {job.supersededBy && <p className="analysis__notice">This historical report used the earlier same-performance assumption. You clarified that these are separate repetitions. <a className="link" href={`?job=${encodeURIComponent(job.supersededBy)}`}>Open the corrected movement-similarity report.</a></p>}
          <div className="analysis__notice"><strong>{similarity ? 'Capture accuracy cannot be determined from these recordings' : 'Statistical equivalence not established'}</strong><p>{similarity ? 'These are separate or unverified performances. Scores describe movement similarity and include differences in how the action was performed. They cannot prove which capture method is more accurate.' : `This report describes one performance. Timing ${summary.timing_status === 'indeterminate' ? 'remains unverified' : 'uses your verified event annotations'}; thresholds are exploratory.`}</p></div>
          {summary.qc.issues.length > 0 && <div className="analysis__review"><h3>Review before interpreting</h3><ul>{summary.qc.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul></div>}
        </div>
      </details>

      {/* Action Shape and Finger Articulation (Keep Visible!) */}
      <ActionShapeResult result={summary.action_shape} jobId={job.jobId} />

      {available ? <>
        <h3>Overall Accuracy Assessment</h3>
        
        {/* Primary Statistical Overview */}
        {analysis.comparison?.single_trial_statistics && !analysis.comparison.single_trial_statistics.error && (
          <div className="analysis__notice" style={{ display: 'flex', gap: '1rem', marginTop: '1rem', marginBottom: '2rem', backgroundColor: 'inherit', padding: 0, border: 'none' }}>
            {analysis.comparison?.single_trial_angle_statistics && !analysis.comparison.single_trial_angle_statistics.error && (
              <div style={{ flex: 1, padding: '1rem', border: '1px solid #4ade80', backgroundColor: analysis.comparison.single_trial_angle_statistics.p_value_one_sided < 0.05 ? 'rgba(74, 222, 128, 0.15)' : 'inherit', borderRadius: '0.25rem' }}>
                <strong style={{ display: 'block', marginBottom: '0.5rem' }}>3D Kinematics (Entire Upper Body)</strong>
                <p style={{ margin: 0, fontWeight: 'bold', color: analysis.comparison.single_trial_angle_statistics.p_value_one_sided < 0.05 ? '#4ade80' : 'inherit' }}>
                  {analysis.comparison.single_trial_angle_statistics.p_value_one_sided < 0.05 ? 'Rokoko Significantly Better' : 'Tie / Not Significant'} 
                  {' '}(p = {analysis.comparison.single_trial_angle_statistics.p_value_one_sided.toFixed(4)})
                </p>
                <small style={{ display: 'block', marginTop: '0.5rem', lineHeight: 1.3 }}>Immune to skeleton stretching. Measures true physical posture.</small>
              </div>
            )}

            <div style={{ flex: 1, padding: '1rem', border: '1px solid #555', backgroundColor: analysis.comparison.single_trial_statistics.p_value_one_sided < 0.05 ? 'rgba(74, 222, 128, 0.15)' : 'inherit', borderRadius: '0.25rem' }}>
              <strong style={{ display: 'block', marginBottom: '0.5rem' }}>2D Video Projection (Position)</strong>
              <p style={{ margin: 0, fontWeight: 'bold', color: analysis.comparison.single_trial_statistics.p_value_one_sided < 0.05 ? '#4ade80' : 'inherit' }}>
                {analysis.comparison.single_trial_statistics.p_value_one_sided < 0.05 ? 'Rokoko Significantly Better' : 'Tie / Not Significant'}
                {' '}(p = {analysis.comparison.single_trial_statistics.p_value_one_sided.toFixed(4)})
              </p>
              <small style={{ display: 'block', marginTop: '0.5rem', lineHeight: 1.3 }}>Prone to 2D scaling artifacts and camera bias.</small>
            </div>
          </div>
        )}

        {/* Primary Graph */}
        <figure className="analysis__figure">
          <img src={api.analysisFile(job.jobId, 'phase_normalized_position_errors.png')} alt={`Position ${metricName} curves`} />
        </figure>

        {/* Hide Raw Positional Metrics in Details */}
        <details className="analysis__advanced" style={{ marginTop: '2rem' }}>
          <summary>Raw Positional Metrics & Camera Diagnostics</summary>
          <div style={{ marginTop: '1rem' }}>
            {summary.skeleton_proportions && <div><p><strong>Why skeleton proportions affect the scores:</strong> The exported skeletons may have different body proportions. These native 3D lengths are divided by each skeleton’s shoulder width. Position differences include those proportions as well as movement and camera projection.</p><div className="analysis__table-wrap"><table className="jobs"><caption>Native segment length / shoulder width</caption><thead><tr><th>Segment</th><th>MotionCapture</th><th>Old FBX</th></tr></thead><tbody>{Object.keys(summary.skeleton_proportions.suit.lengths_per_shoulder_width).map((name) => <tr key={name}><th scope="row">{name.replaceAll('_', ' ')}</th><td>{format(summary.skeleton_proportions.suit.lengths_per_shoulder_width[name])}</td><td>{format(summary.skeleton_proportions.non_suit.lengths_per_shoulder_width[name])}</td></tr>)}</tbody></table></div></div>}
            
            <div className="analysis__metrics" style={{ marginTop: '2rem' }}>
              {['suit', 'non_suit'].map((key) => <div key={key}><span>{key === 'suit' ? 'MotionCapture FBX' : 'Old FBX'}</span><strong>{format(analysis.methods[key].combined_position.mean)}</strong><small>Mean position {metricName} / shoulder width</small>{sensitivity.unresolved && <small>Across plausible camera fits: <b>{formatRange(sensitivity.error_ranges[key])}</b></small>}</div>)}
              <div><span>{similarity ? 'Capture accuracy ranking' : 'Old − MotionCapture'}</span><strong>{similarity ? 'Not assessable' : sensitivity.ranking_changes ? 'Unresolved' : format(analysis.comparison.combined_position.old_minus_motioncapture)}</strong><small>{similarity ? 'Requires a matching reference for each performance' : sensitivity.ranking_changes ? 'Camera fits give different rankings' : 'Positive values favour MotionCapture'}</small>{sensitivity.unresolved && <small>Movement difference range: <b>{formatRange(sensitivity.old_minus_motioncapture_range)}</b></small>}</div>
            </div>
            
            <p className="hint">Shape comparison after stretching each clip to the same action phases. Mean {metricName} combines both wrists and elbows; it does not measure timing agreement.</p>
            {sensitivity.unresolved && <p className="hint">The numeric means and per-joint values use the camera fit with the smallest torso calibration error. The ranges show other plausible fits; they are sensitivity ranges, not confidence intervals.</p>}
            {analysis.calibration_sensitivity.ranking_changes && <p className="field-error">The method ranking changes across plausible camera calibrations. The displayed difference is not a reliable winner.</p>}
            {analysis.frontal_camera_diagnostic && <details className="analysis__advanced"><summary>Frontal-view sensitivity — assumed camera</summary><p>{analysis.frontal_camera_diagnostic.interpretation}</p><div className="analysis__table-wrap"><table className="jobs"><caption>Mean position difference / shoulder width under the frontal assumption</caption><thead><tr><th>Method</th><th>Difference</th></tr></thead><tbody>{Object.entries(analysis.frontal_camera_diagnostic.methods).map(([key, item]) => <tr key={key}><th scope="row">{key === 'suit' ? 'MotionCapture FBX' : 'Old FBX'}</th><td>{item.metrics ? format(item.metrics.combined_position.mean) : item.reason}</td></tr>)}</tbody></table></div><p>These values do not replace the primary scores. A change in ranking shows how strongly the camera assumption affects this comparison.</p></details>}
            
            <div className="analysis__table-wrap"><table className="jobs"><caption>Per-joint mean position {metricName} in reference shoulder widths</caption><thead><tr><th>Joint</th><th>MotionCapture</th><th>Old FBX</th><th>Old − MotionCapture</th></tr></thead><tbody>
              {Object.keys(analysis.comparison.position).map((joint) => <tr key={joint}><th scope="row">{joint.replaceAll('_', ' ')}</th><td>{format(analysis.methods.suit.position[joint].mean)}</td><td>{format(analysis.methods.non_suit.position[joint].mean)}</td><td>{format(analysis.comparison.position[joint].old_minus_motioncapture)}</td></tr>)}
            </tbody></table></div>
          </div>
        </details>

        {summary.artifacts.comparison_overlay && <details className="analysis__advanced"><summary>Inspect both FBX projections against the video</summary><figure className="analysis__figure"><img loading="lazy" src={api.analysisFile(job.jobId, summary.artifacts.comparison_overlay)} alt="Video landmarks, MotionCapture FBX, and old FBX projected over five video frames" /><figcaption>The displayed camera fits at matching percentages of each action. Separate repetitions may differ at those phases; this is a visual similarity check.</figcaption></figure></details>}
      </> : <p className="error" role="status">No shape scores were produced: {analysis.reason}</p>}
      
      <div className="analysis__downloads">
        <button type="button" className="button" onClick={() => setShowReport((value) => !value)} aria-expanded={showReport} aria-controls="analysis-full-report">{showReport ? 'Hide complete report' : 'View complete report'}</button>
        {[['report.html', 'Download report'], ['summary.json', 'Download results'], ['manifest.json', 'Download annotations'], ...Object.values(summary.artifacts.traces).map((name) => [name, ({ synchronized_traces: 'Download timing traces', phase_normalized_traces: 'Download position traces', action_shape_traces: 'Download action angles', action_alignment: 'Download time alignment', finger_animation_traces: 'Download finger articulation' })[name.replace('.csv', '')] || 'Download traces'])].map(([name, label]) => <a className="link" key={name} href={api.analysisFile(job.jobId, name, true)}>{label}</a>)}
      </div>
      {showReport && <iframe id="analysis-full-report" className="analysis__report" src={api.analysisFile(job.jobId, 'report.html')} title="Complete video–FBX agreement report" sandbox="" />}
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
    if (key === 'video') setVideoUrl(file ? URL.createObjectURL(file) : null)
    setError(null)
  }
  function updateTiming(key, field, value) {
    setTiming((current) => ({ ...current, [key]: { ...current[key], [field]: value } }))
  }
  async function submit(event) {
    event.preventDefault()
    setError(null)
    try {
      const options = buildAnalysisOptions({ files, action, pairing, relationship, windows, calibration, verifiedTiming, timing })
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
        <div className="analysis__intro"><h2>From recording to evidence.</h2><p>Upload a real-person video and both FBX recordings. Matching performances support agreement checks; separate repetitions support movement similarity. Compare wrist and elbow paths, joint angles, and recording quality.</p></div>
        {readiness && !readiness.ready && <p className="error" role="alert">{readiness.message}</p>}
        <form onSubmit={submit}>
          <fieldset disabled={!!busy} className="analysis__form"><legend className="analysis__eyebrow">01 · Select the sources</legend>
            <label className="field">Comparison name<input value={action} onChange={(e) => setAction(e.target.value)} maxLength={120} placeholder="For example: ACTION — take 01" /></label>
            <label className="field">How were these recordings made?<select value={relationship} onChange={(e) => { setRelationship(e.target.value); setPairing(false); setVerifiedTiming(false) }}><option value="unknown">I’m not sure — movement similarity only</option><option value="separate_repetitions">Separate repetitions of the same action — movement similarity</option><option value="same_performance">One simultaneous performance — agreement comparison</option></select></label>
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
              {verifiedTiming && ['suit', 'non_suit'].map((key) => <div className="analysis__timing" key={key}><h3>{key === 'suit' ? 'MotionCapture FBX' : 'Old FBX'} synchronization</h3>
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
