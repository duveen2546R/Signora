import { assertPayloadShape } from '../unity/canonicalFrame.js'

// "neutral-fallback" means a pair that no direct transition could join plays through the rest
// pose instead; every leg of it still passed the backend's motion checks.
// "reviewed-direct" means a reviewed recording captured slightly short settles to or from rest;
// the backend kept every integrity check mandatory and lists the boundary checks it waived.
export const PLAYABLE_BLEND_STATUSES = new Set(['direct', 'neutral-fallback', 'reviewed-direct'])

/**
 * A seam may play when it passed the strict gate, or when it is a settle whose failures the backend
 * explicitly waived (`waivedChecks`). A seam that merely failed - including a neutral-fallback seam
 * with no settle leg - is still refused.
 */
export function seamPlayable(seam) {
  if (!seam || !PLAYABLE_BLEND_STATUSES.has(seam.mode)) return false
  if (seam.passed === true) return true
  const settled = seam.mode === 'reviewed-direct' || (seam.legModes ?? []).includes('reviewed-direct')
  return settled && Array.isArray(seam.waivedChecks)
}

export function playableTrack(result) {
  if (!['ready', 'preview', 'literal-preview'].includes(result?.translationStatus) || !PLAYABLE_BLEND_STATUSES.has(result?.blendQuality?.status) || result?.error) return null
  if (!result.track || !PLAYABLE_BLEND_STATUSES.has(result.track.blendQuality?.status)) return null
  if (result.blendQuality.seams?.some((seam) => !seamPlayable(seam))) return null
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

/** One line naming the reviewed recordings that settle to or from rest, or null when none do. */
export function settleNotice(blendQuality) {
  const edges = (blendQuality?.seams ?? [])
    .filter((seam) => seam.mode === 'reviewed-direct' || (seam.legModes ?? []).includes('reviewed-direct'))
    .map((seam) => `${seam.fromGloss || 'rest'} → ${seam.toGloss || 'rest'}`)
  if (!edges.length) return null
  return `Reviewed recording${edges.length === 1 ? '' : 's'} captured starting or ending in motion; settling to or from rest at ${edges.join(', ')}.`
}

export function blendNotices(result) {
  const notices = [...(result?.warnings ?? []), ...(result?.issues ?? []).map((issue) => issue.message)]
  if (result?.blendQuality?.status === 'reviewed-direct') {
    notices.unshift(fallbackNotice(result.blendQuality), settleNotice(result.blendQuality))
  } else if (result?.blendQuality?.status === 'neutral-fallback') {
    notices.unshift(fallbackNotice(result.blendQuality))
  } else if (result?.blendQuality && result.blendQuality.status !== 'direct') {
    const pairs = (result.blendQuality.seams ?? [])
      .filter((seam) => seam.mode !== 'direct' || seam.passed !== true)
      .map((seam) => `${seam.fromGloss || 'rest'} → ${seam.toGloss || 'rest'}`)
    notices.unshift(`Playback blocked. Review transition${pairs.length === 1 ? '' : 's'}${pairs.length ? `: ${pairs.join(', ')}` : ' and phase timestamps'}.`)
  }
  return [...new Set(notices.filter(Boolean))]
}
