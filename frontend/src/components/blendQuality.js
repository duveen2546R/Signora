import { assertPayloadShape } from '../unity/canonicalFrame.js'

// "neutral-fallback" means a pair that no direct transition could join plays through the rest
// pose instead; every leg of it still passed the backend's motion checks.
export const PLAYABLE_BLEND_STATUSES = new Set(['direct', 'neutral-fallback'])

export function playableTrack(result) {
  if (!['ready', 'preview', 'literal-preview'].includes(result?.translationStatus) || !PLAYABLE_BLEND_STATUSES.has(result?.blendQuality?.status) || result?.error) return null
  if (!result.track || !PLAYABLE_BLEND_STATUSES.has(result.track.blendQuality?.status)) return null
  if (result.blendQuality.seams?.some((seam) => seam.passed !== true || !PLAYABLE_BLEND_STATUSES.has(seam.mode))) return null
  try {
    assertPayloadShape(result.track)
    return result.track
  } catch { return null }
}

/** One line naming the pairs that pass through the rest pose, or null when every join is direct. */
export function fallbackNotice(blendQuality) {
  const pairs = (blendQuality?.seams ?? [])
    .filter((seam) => seam.mode === 'neutral-fallback')
    .map((seam) => `${seam.fromGloss} → ${seam.toGloss}`)
  if (!pairs.length) return null
  return `No direct transition passed for ${pairs.join(', ')}, so the avatar returns to rest between ${pairs.length === 1 ? 'those signs' : 'each of those pairs'}.`
}

export function blendNotices(result) {
  const notices = [...(result?.warnings ?? []), ...(result?.issues ?? []).map((issue) => issue.message)]
  if (result?.blendQuality?.status === 'neutral-fallback') {
    notices.unshift(fallbackNotice(result.blendQuality))
  } else if (result?.blendQuality && result.blendQuality.status !== 'direct') {
    const pairs = (result.blendQuality.seams ?? [])
      .filter((seam) => seam.mode !== 'direct' || seam.passed !== true)
      .map((seam) => `${seam.fromGloss || 'rest'} → ${seam.toGloss || 'rest'}`)
    notices.unshift(`Playback blocked. Review transition${pairs.length === 1 ? '' : 's'}${pairs.length ? `: ${pairs.join(', ')}` : ' and phase timestamps'}.`)
  }
  return [...new Set(notices.filter(Boolean))]
}
