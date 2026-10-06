import { api } from '../api/client'

const number = (value) => Number.isFinite(value) ? value.toFixed(2) : '—'

export default function ActionShapeResult({ result, jobId }) {
  if (!result) return null
  if (result.status !== 'exploratory') return <section className="analysis__review"><h3>Upper-body action shape</h3><p>{result.reason}</p></section>
  return <section className="analysis__review action-shape" aria-labelledby="action-shape-heading">
    <h3 id="action-shape-heading">Upper-body action shape — allowing timing differences</h3>
    <p>We compare the direction and bending of body segments, with limited time alignment shared by all body parts. This reduces the effect of different limb lengths. Lower angular differences mean closer visible shapes.</p>
    <p className="analysis__notice">{result.limits}</p>
    {Object.keys(result.hand_animation_diagnostics).length > 0 && <div className="analysis__table-wrap"><table className="jobs"><caption>Finger articulation stored in each FBX — maximum joint-bend change during the action</caption><thead><tr><th>Hand</th><th>MotionCapture</th><th>Old FBX</th></tr></thead><tbody>{['left', 'right'].map((side) => <tr key={side}><th scope="row">{side}</th>{['suit', 'non_suit'].map((label) => <td key={label}>{number(result.hand_animation_diagnostics[`${label}_${side}`]?.maximum_bend_excursion_deg)}°{result.hand_animation_diagnostics[`${label}_${side}`]?.effectively_fixed_bends && ' — effectively fixed bends'}</td>)}</tr>)}</tbody></table><p>These are native 3D bend changes in the exported files. More movement does not by itself mean greater accuracy. Changes below 1° are flagged as effectively fixed for this diagnostic; this is not an agreement threshold.</p></div>}
    <div className="analysis__table-wrap"><table className="jobs">
      <caption>Mean angular difference in degrees. Ranges show sensitivity to camera calibration.</caption>
      <thead><tr><th>Body part</th><th>MotionCapture</th><th>Old FBX</th><th>Common coverage</th><th>Assessment</th></tr></thead>
      <tbody>{result.regions.map((row) => <tr key={row.region}>
        <th scope="row">{row.region}</th>
        {['suit', 'non_suit'].map((label) => <td key={label}>{number(row.methods[label]?.mean)}{row.methods[label]?.camera_range && <small className="hint"> ({row.methods[label].camera_range.map(number).join('–')})</small>}</td>)}
        <td>{Number.isFinite(row.common_coverage) ? `${Math.round(row.common_coverage * 100)}%` : '—'}</td>
        <td>{row.reason || (row.status === 'insufficient_coverage' ? 'Too few reliable reference samples' : row.ranking_changes_with_camera ? 'Ranking changes with camera' : 'Provisional 2D comparison')}</td>
      </tr>)}</tbody>
    </table></div>
    <details className="analysis__advanced"><summary>Inspect timing adjustment and direction curves</summary>
      <p>{result.method} The alignment can shift by at most {Math.round(result.alignment_policy.band_fraction * 100)}% of the selected action. Timing agreement remains a separate measurement.</p>
      <figure className="analysis__figure"><img loading="lazy" src={api.analysisFile(jobId, 'action_shape.png')} alt="Shared time alignment for both FBX methods and left and right forearm angular difference curves" /></figure>
      <a className="link" href={api.analysisFile(jobId, 'action_shape.png')} target="_blank" rel="noreferrer">Open larger direction chart</a>
      <ul>{Object.entries(result.alignment_diagnostics).map(([label, values]) => <li key={label}>{label === 'suit' ? 'MotionCapture' : 'Old FBX'}: arm direction difference {number(values.before_local_alignment_arm_mean_deg)}° before local timing alignment; {number(values.after_local_alignment_arm_mean_deg)}° after. Largest phase shift: {number(values.max_phase_shift * 100)}%.</li>)}</ul>
    </details>
    {Object.keys(result.hand_animation_diagnostics).length > 0 && <details className="analysis__advanced"><summary>Inspect finger bending stored in the files</summary><figure className="analysis__figure"><img loading="lazy" src={api.analysisFile(jobId, 'finger_animation.png')} alt="Native middle-joint bend curves for all five fingers on both hands, comparing the two FBX files" /></figure><a className="link" href={api.analysisFile(jobId, 'finger_animation.png')} target="_blank" rel="noreferrer">Open larger finger chart</a></details>}
  </section>
}
