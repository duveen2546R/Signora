import { useEffect, useState } from 'react'
import { api } from '../api/client'
import MotionPhaseEditor from '../components/MotionPhaseEditor'
import { inspectCaptureDuration, phaseDurations, snapPhaseDraft, validatePhaseDraft } from '../capturePhases'

/** Upload rig profiles and motion captures, and watch ingest results come back. */
export default function Capture({ onLibraryChanged }) {
  const [rigs, setRigs] = useState([])
  const [jobs, setJobs] = useState([])
  const [drafts, setDrafts] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => { api.listRigs().then(setRigs).catch((e) => setError(e.message)) }, [])

  // Poll while anything is still ingesting.
  useEffect(() => {
    const pending = jobs.filter((j) => j.status === 'pending')
    if (pending.length === 0) return
    const timer = setInterval(async () => {
      const updated = await Promise.all(
        jobs.map((j) => (j.status === 'pending' ? api.captureStatus(j.jobId).catch(() => j) : j)),
      )
      setJobs(updated)
      if (updated.some((j) => j.status === 'done')) onLibraryChanged?.()
    }, 1000)
    return () => clearInterval(timer)
  }, [jobs, onLibraryChanged])

  async function handleRig(event) {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      await api.uploadRig(file)
      setRigs(await api.listRigs())
      setError(null)
    } catch (e) { setError(e.message) }
  }

  async function selectCaptures(event) {
    const files = Array.from(event.target.files ?? [])
    const inspected = await Promise.all(files.map(async (file) => {
      try {
        await inspectCaptureDuration(file)
        const track = await api.previewCapture(file)
        const duration = track.durationSeconds ?? track.frameCount / track.fps
        return {
          id: `${file.name}-${file.lastModified}-${crypto.randomUUID()}`,
          file, track, duration, signStart: track.signStartSeconds ?? '', signEnd: track.signEndSeconds ?? '',
          touched: false, error: null, uploading: false,
        }
      } catch (e) {
        return { id: `${file.name}-${crypto.randomUUID()}`, file, error: e.message, invalid: true }
      }
    }))
    setDrafts((previous) => [...previous, ...inspected])
    event.target.value = ''
  }

  function updateDraft(id, update) {
    setDrafts((previous) => previous.map((draft) => (
      draft.id === id ? { ...draft, ...update } : draft
    )))
  }

  async function uploadDraft(id) {
    const draft = drafts.find((item) => item.id === id)
    if (!draft || draft.invalid) return
    const validation = validatePhaseDraft(draft)
    if (validation) {
      updateDraft(id, { touched: true, error: validation })
      return
    }
    updateDraft(id, { uploading: true, error: null })
    try {
      const snapped = snapPhaseDraft(draft)
      const phases = {
        signStartSeconds: snapped.signStart,
        signEndSeconds: snapped.signEnd,
      }
      const job = await api.uploadCapture(draft.file, phases)
      setJobs((previous) => [{ ...job, name: draft.file.name }, ...previous])
      setDrafts((previous) => previous.filter((item) => item.id !== id))
      setError(null)
    } catch (e) {
      updateDraft(id, { uploading: false, error: e.message })
    }
  }

  return (
    <section className="capture">
      <header className="page-masthead">
        <p>02 / Capture</p>
        <h1>Teach every<br />movement.</h1>
        <span>Build the vocabulary<br />one performance at a time.</span>
      </header>
      <div className="panel">
        <h2>Avatar rig</h2>
        <p className="hint">
          Export once from Unity: select the avatar, then <code>SignSure &gt; Export Rig Profile</code>.
          Motion cannot be retargeted until this is uploaded.
        </p>
        <input type="file" accept=".json" onChange={handleRig} />
        <ul className="rigs">
          {rigs.map((rig) => (
            <li key={rig.digest}>
              <strong>{rig.avatarName}</strong>
              <span className="mono">{rig.digest}</span>
              <span>hip height {rig.hipHeight?.toFixed?.(2)}m</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="panel">
        <h2>Motion captures</h2>
        <p className="hint">
          Rokoko biomechanics CSV exports. Name each file for the sign it contains
          (<code>hello_01.csv</code>) — the gloss and take number are read from the filename.
        </p>
        <label className="capture__picker">
          <span>Select motion captures</span>
          <input type="file" accept=".csv" multiple onChange={selectCaptures} />
        </label>

        {drafts.length > 0 && (
          <div className="phase-drafts" aria-label="Capture phase timestamps">
            {drafts.map((draft) => {
              const durations = draft.invalid ? null : phaseDurations(draft)
              return (
                <fieldset className="phase-draft" key={draft.id} disabled={draft.uploading}>
                  <legend>{draft.file.name}</legend>
                  {draft.invalid ? (
                    <>
                      <p className="field-error" role="alert">{draft.error}</p>
                      <div className="phase-draft__actions">
                        <button type="button" className="secondary" onClick={() => setDrafts((items) => items.filter((item) => item.id !== draft.id))}>
                          Remove
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="phase-draft__duration">Capture duration: {draft.duration.toFixed(3)}s</p>
                      <p className="hint">
                        Split the capture into three sections by entering the two boundary timestamps.
                      </p>
                      <MotionPhaseEditor
                        track={draft.track} signStart={draft.signStart} signEnd={draft.signEnd}
                        disabled={draft.uploading}
                        onChange={(change) => updateDraft(draft.id, { ...change, error: null })}
                      />
                      {durations && (
                        <p className="phase-draft__summary">
                          Start: 0.000–{durations.start.toFixed(3)}s · Sign: {durations.start.toFixed(3)}–{Number(draft.signEnd).toFixed(3)}s · End: {Number(draft.signEnd).toFixed(3)}–{draft.duration.toFixed(3)}s
                        </p>
                      )}
                      {draft.error && (
                        <p id={`${draft.id}-error`} className="field-error" role="alert">{draft.error}</p>
                      )}
                      <div className="phase-draft__actions">
                        <button type="button" className="secondary" onClick={() => setDrafts((items) => items.filter((item) => item.id !== draft.id))}>
                          Remove
                        </button>
                        <button type="button" onClick={() => uploadDraft(draft.id)}>
                          {draft.uploading ? 'Uploading…' : 'Upload capture'}
                        </button>
                      </div>
                    </>
                  )}
                </fieldset>
              )
            })}
          </div>
        )}

        {jobs.length > 0 && (
          <table className="jobs">
            <thead>
              <tr><th>File</th><th>Gloss</th><th>Status</th><th>Notes</th></tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.jobId}>
                  <td className="mono">{job.name}</td>
                  <td>{job.gloss}</td>
                  <td><span className={`status status--${job.status}`}>{job.status}</span></td>
                  <td className="notes">
                    {job.error}
                    {job.qc?.warnings?.join('; ')}
                    {job.status === 'done' && !job.qc?.warnings?.length &&
                      `${job.qc?.dominant_hand} hand, ${job.qc?.duration?.toFixed?.(1)}s`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {error && <p className="error">{error}</p>}
    </section>
  )
}
