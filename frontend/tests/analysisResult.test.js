import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

test('analysis results render single, dual, missing-data, and historical certificates', async () => {
  const server = await createServer({ server: { middlewareMode: true, watch: null, hmr: false, ws: false }, appType: 'custom' })
  try {
    const { Result } = await server.ssrLoadModule('/src/pages/Analysis.jsx')
    const domain = { domain: 'Handshape', status: 'INCONCLUSIVE', margin: .1, max_deviation: null }
    const certificate = { label: 'MotionCaptureFBX', decision: 'INCONCLUSIVE', domains: { handshape: domain } }
    const render = (equivalence, overrides = {}) => renderToStaticMarkup(createElement(Result, { job: {
      jobId: 'test', summary: { performance_id: 'Test', comparison_kind: 'movement_similarity', qc: { issues: [] }, artifacts: { traces: {} },
        analyses: { phase_normalized: { status: 'descriptive', comparison: { equivalence } } }, ...overrides,
      },
    } }))
    assert.match(render({ suit: certificate }), /INCONCLUSIVE/)
    const historical = render({ suit: { ...certificate, decision: 'EQUIVALENT' } })
    assert.match(historical, /Historical report/)
    assert.match(historical, /Observed tolerance satisfied/)
    assert.match(historical, /Statistical equivalence not established/)
    const current = render({ suit: { ...certificate, profile_sensitivity: { replication: certificate, intelligibility: certificate }, required_joint_coverage: { left_index: 0 }, hand_coverage: { left: 0, right: 1 }, camera_sensitivity: { interpretation: 'Not confidence intervals', domain_ranges: { handshape: null } } } }, { assessment_kind: 'observed_tolerance', alignment_sensitivity: { interpretation: 'Resolution only', scenarios: [] }, artifacts: { traces: {}, full_sequence_overlay: 'full_sequence_overlay.mp4' } })
    assert.doesNotMatch(current, /Historical report/)
    assert.match(current, /Timing resolution sensitivity/)
    assert.match(current, /Wider legacy profile/)
    assert.match(current, /Complete sample coverage/)
    assert.match(current, /Insufficient coverage/)
    assert.match(current, /full_sequence_overlay.mp4/)

    assert.match(render({ suit: certificate, non_suit: { ...certificate, label: 'oldFBX' } }), /oldFBX/)
    const synchronized = render(undefined, { primary_analysis: 'synchronized', analyses: {
      phase_normalized: { status: 'indeterminate' },
      synchronized: { status: 'descriptive', reference_view: 'front', comparison: { equivalence: { suit: certificate } } },
    } })
    assert.match(synchronized, /Declared or estimated synchronized timing/)
    assert.match(synchronized, /Front view/)
    assert.match(synchronized, /INCONCLUSIVE/)
    assert.match(render(undefined), /no domain certificates/)
    assert.match(render({ error: 'Missing landmarks' }), /Domain evaluation unavailable: Missing landmarks/)
    assert.match(render({ suit: { ...certificate, domains: { handshape: { ...domain, max_deviation: undefined } } } }), /INCONCLUSIVE/)

    // Trajectory and elbow angles graphs rendering
    const withGraphs = render(undefined, {
      artifacts: {
        trajectories_plot: 'synchronized_trajectories.png',
        angles_plot: 'synchronized_angles.png',
      },
    })
    assert.match(withGraphs, /FIGURE 4\.5/)
    assert.match(withGraphs, /FIGURE 4\.6/)
    assert.match(withGraphs, /synchronized_trajectories\.png/)
    assert.match(withGraphs, /synchronized_angles\.png/)
  } finally {
    await server.close()
  }
})

test('single-take equivalence results show every verdict, the claim and its scope', async () => {
  const server = await createServer({ server: { middlewareMode: true, watch: null, hmr: false, ws: false }, appType: 'custom' })
  try {
    const { Result } = await server.ssrLoadModule('/src/pages/Analysis.jsx')
    const angle = (decision) => ({ decision, margin_deg: 5, mean_difference_deg: 0.4, mean_ci_deg: [-1.2, 2.0], mean_decision: 'EQUIVALENT', rms_deg: 2.1, rms_ci_deg: [1.0, 3.6], rms_decision: decision, curve_decision: 'INCONCLUSIVE', max_band_abs_deg: 18.2, replicate_check: { pass: true } })
    const render = (decision) => renderToStaticMarkup(createElement(Result, { job: { jobId: 'job', summary: {
      performance_id: 'Father', equivalence_verdict: decision, message: 'Verdict message', message_detail: 'Detail',
      single_take: { decision, primary_claim: 'rms', scope: 'Conditional on this performance only.', angles: { left_elbow_flexion: angle(decision), right_elbow_flexion: angle(decision) }, noise_model: { source: 'max(still frames, replicate spread)' }, diagnostics: { baseline_angle_deg: 36.1, reprojection_rms_px: 2.3 } },
      artifacts: { single_take_plot: 'single_take_equivalence.png', single_take_report: 'single_take_report.json', figures: ['single_take_equivalence.png'] },
    } } }))
    for (const decision of ['EQUIVALENT', 'NOT EQUIVALENT', 'INCONCLUSIVE']) assert.match(render(decision), new RegExp(decision))
    const html = render('INCONCLUSIVE')
    assert.match(html, /RMS difference/)
    assert.match(html, /Conditional on this performance only/)
    assert.match(html, /single_take_equivalence\.png/)
    assert.match(html, /single_take_report\.json/)
    assert.match(html, /left elbow flexion/)
    assert.doesNotMatch(html, /fTOST|PROVEN/)
  } finally {
    await server.close()
  }
})
