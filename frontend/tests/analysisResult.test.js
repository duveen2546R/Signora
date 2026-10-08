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
  } finally {
    await server.close()
  }
})
