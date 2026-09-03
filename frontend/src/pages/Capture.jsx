import { useEffect, useState } from 'react'
import { api } from '../api/client'

/** Upload rig profiles and motion captures, and watch ingest results come back. */
export default function Capture({ onLibraryChanged }) {
  const [rigs, setRigs] = useState([])
  const [jobs, setJobs] = useState([])
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

  async function handleCaptures(event) {
    const files = Array.from(event.target.files ?? [])
    for (const file of files) {
      try {
        const job = await api.uploadCapture(file)
        setJobs((prev) => [{ ...job, name: file.name }, ...prev])
        setError(null)
      } catch (e) { setError(e.message) }
    }
    event.target.value = ''
  }

  return (
    <section className="capture">
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
        <input type="file" accept=".csv" multiple onChange={handleCaptures} />

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
