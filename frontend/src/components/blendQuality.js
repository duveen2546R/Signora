export function playableTrack(result) {
  return result?.track ?? null
}

export function blendNotices(result) {
  // Keep the sentence panel concise even when talking to an older backend that still returns one
  // automatic-phase advisory per word. Newer backends already return one grouped advisory.
  const warnings = result?.warnings ?? []
  const automaticPhase = warnings.filter((warning) =>
    warning.includes('uses automatically detected phase boundaries'),
  )
  const notices = warnings.filter((warning) =>
    !warning.includes('uses automatically detected phase boundaries'),
  )
  if (automaticPhase.length) {
    const glosses = [...new Set(automaticPhase.map((warning) => warning.split(' uses ')[0]))]
    const noun = glosses.length === 1 ? 'capture' : 'captures'
    notices.unshift(
      `Using safe full-motion fallback for unreviewed ${noun}: ${glosses.join(', ')}. ` +
      'Add sign-start and sign-end timestamps to enable position-aware trimming.',
    )
  }
  if (result?.blendQuality?.status === 'neutral-fallback') {
    notices.unshift(
      'One or more sign transitions could not be blended directly. A smooth neutral-pose ' +
      'bridge was used to keep the motion safe and readable.',
    )
  }

  // A sentence always plays. When no bridge clears the quality envelope the best available one is
  // used anyway - an imperfect transition is worth far more than a motionless avatar and an error -
  // but the signs involved are named so the captures can be reviewed.
  if (result?.blendQuality?.status === 'degraded') {
    const affected = (result?.blendQuality?.seams ?? [])
      .filter((seam) => String(seam.mode ?? '').startsWith('degraded'))
      .map((seam) => `${seam.fromGloss || 'rest'} to ${seam.toGloss || 'rest'}`)
    notices.unshift(
      'Some transitions were rougher than the quality target and played as recorded' +
      (affected.length ? `: ${affected.join(', ')}` : '') +
      '. Re-recording those signs with a clearer pause at the boundary will smooth them.',
    )
  }
  return notices
}
