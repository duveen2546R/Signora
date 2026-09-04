export function playableTrack(result) {
  return result?.track ?? null
}

export function blendNotices(result) {
  const notices = [...(result?.warnings ?? [])]
  if (result?.blendQuality?.status === 'neutral-fallback') {
    notices.unshift(
      'One or more sign transitions could not be blended directly. A smooth neutral-pose ' +
      'bridge was used to keep the motion safe and readable.',
    )
  }
  return notices
}
