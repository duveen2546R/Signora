import { assertPayloadShape } from '../unity/canonicalFrame.js'

export function playableTrack(result) {
  if (!['ready', 'preview'].includes(result?.translationStatus) || result?.blendQuality?.status !== 'direct' || result?.error) return null
  if (!result.track || result.track.blendQuality?.status !== 'direct') return null
  if (result.blendQuality.seams?.some((seam) => seam.passed !== true || seam.mode !== 'direct')) return null
  try {
    assertPayloadShape(result.track)
    return result.track
  } catch { return null }
}

export function blendNotices(result) {
  const notices = [...(result?.warnings ?? []), ...(result?.issues ?? []).map((issue) => issue.message)]
  if (result?.blendQuality && result.blendQuality.status !== 'direct') {
    const pairs = (result.blendQuality.seams ?? [])
      .filter((seam) => seam.mode !== 'direct' || seam.passed !== true)
      .map((seam) => `${seam.fromGloss || 'rest'} → ${seam.toGloss || 'rest'}`)
    notices.unshift(`Playback blocked. Review transition${pairs.length === 1 ? '' : 's'}${pairs.length ? `: ${pairs.join(', ')}` : ' and phase timestamps'}.`)
  }
  return [...new Set(notices.filter(Boolean))]
}
