/**
 * Pure decision logic for progressive video-plan consumption.
 *
 * Why this exists: `backend/app/services/video_plan_service.py::prepare_plan` already commits
 * each unit to the database as it finishes (confirmed by polling `GET /video-plans/{id}` mid-run
 * against a live backend: unit 0 showed `motionAvailable: true` within 3 s while the plan overall
 * stayed `status: "processing"` for minutes). So nothing on the backend needed to change for
 * progressive readiness - the problem was entirely that the extension waited for
 * `plan.status === 'ready'` before doing anything with that already-available data.
 *
 * These functions turn a sequence of polled plan snapshots into: which units just became
 * playable, and whether the overlay should say "buffering" right now. Kept framework-free so they
 * are testable without a scheduler, a DOM, or a backend.
 */

export const TERMINAL_PLAN_STATUSES = new Set(['ready', 'failed'])

export function isPlanTerminal(status) {
  return TERMINAL_PLAN_STATUSES.has(status)
}

/**
 * Compare this poll's units against the ids already known to be ready.
 * @returns {{ newlyReady: object[], readyIds: Set<number> }}
 */
export function diffNewlyReady(units, previousReadyIds) {
  const readyIds = new Set(previousReadyIds)
  const newlyReady = []
  for (const unit of units) {
    if (unit.motionAvailable && !readyIds.has(unit.id)) {
      readyIds.add(unit.id)
      newlyReady.push(unit)
    }
  }
  return { newlyReady, readyIds }
}

/**
 * Has the backend finished *deciding* on a unit, whether or not that decision produced playable
 * motion? `status !== 'pending'` covers ready/literal-preview/unsupported/missing-signs/
 * motion-rejected/function-only alike - anything but still-in-the-queue.
 */
function isSettled(unit) {
  return unit.status !== 'pending'
}

/**
 * What the overlay should say right now, purely from timing and readiness - no scheduler
 * required. This is what keeps the UI from ever reading "0/10" forever: it looks at whether
 * *this moment's* caption is ready, not whether *everything* is.
 *
 * @param {number} mediaMs          current video time
 * @param {object[]} units          full unit list (known immediately after POST; times never change)
 * @param {Set<number>} readyIds
 * @param {string} planStatus       'pending' | 'processing' | 'ready' | 'failed'
 * @param {number} lookaheadCount   how many upcoming units count as "the buffer"
 */
export function describeReadiness(mediaMs, units, readyIds, planStatus, lookaheadCount = 2) {
  const current = units.find((u) => mediaMs >= u.startMs && mediaMs < u.endMs) ?? null

  if (current) {
    if (readyIds.has(current.id)) {
      return { state: 'signable', unit: current }
    }
    if (isSettled(current)) {
      // The backend decided this caption has no sign (unsupported/rejected/etc) - that is not
      // "buffering", it is a final, honestly-reported answer.
      return { state: 'unsignable', unit: current }
    }
    return { state: 'buffering-current', unit: current }
  }

  if (!isPlanTerminal(planStatus)) {
    const upcoming = units
      .filter((u) => u.startMs >= mediaMs)
      .sort((a, b) => a.startMs - b.startMs)
      .slice(0, lookaheadCount)
    const pendingLookahead = upcoming.filter((u) => !isSettled(u))
    if (pendingLookahead.length) {
      return { state: 'buffering-lookahead', units: pendingLookahead }
    }
  }

  return { state: 'idle' }
}

/**
 * What the overlay should report as not signed, and how many units played through a labelled
 * transition fallback, from the backend's own per-unit issue reports.
 *
 * A rejected unit is reported as the caption it came from. Blaming each gloss inside it named signs
 * that were never the problem: when "Add all." was rejected only the join into ADD had failed, yet
 * the overlay listed "ALL (motion rejected)". A `motion-fallback` unit is playable motion, so it is
 * counted, never listed as unsupported.
 */
export function summarizeIssues(units) {
  const notSigned = new Set()
  let fallbackUnits = 0
  for (const unit of units ?? []) {
    const issues = unit.issues ?? []
    for (const issue of issues) {
      const words = issue.sourceWords ?? (issue.sourceWord ? [issue.sourceWord] : [])
      for (const word of words) if (word) notSigned.add(String(word))
      if (issue.code === 'motion-rejected') notSigned.add(`“${unit.text}” (motion rejected)`)
    }
    if (unit.motionAvailable && issues.some((issue) => issue.code === 'motion-fallback')) fallbackUnits += 1
  }
  return { notSigned: [...notSigned], fallbackUnits }
}

/** Human-readable coverage summary for the overlay, usable mid-processing. */
export function progressSummary(units, readyIds) {
  const settled = units.filter(isSettled).length
  return {
    total: units.length,
    settled,
    ready: readyIds.size,
  }
}
