/** Make stored gloss labels and ordinary typed text comparable. */
export function normaliseSignSearch(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, ' ')
    .trim()
    .toUpperCase()
}

/**
 * Match each typed word so `good morning` finds `GOOD_MORNING`, while a blank
 * search keeps the complete library visible.
 */
export function filterSigns(signs, query) {
  const terms = normaliseSignSearch(query).split(' ').filter(Boolean)
  if (terms.length === 0) return signs
  return signs.filter((sign) => {
    const label = normaliseSignSearch(sign.gloss)
    return terms.every((term) => label.includes(term))
  })
}
