// Recognition revisions are tracked by word position, never deduplicated by text:
// saying "hello hello" really must produce two signs.
export const STABLE_PREFIX_MS = 220
export const STABLE_TAIL_MS = 350
const PHRASE_LOOKAHEAD_MS = 550

export function speechWords(text) {
  return text.normalize('NFKC').toLowerCase().replaceAll('’', "'")
    .replace(/[,;.!]+/g, ' ').trim().split(/\s+/).filter(Boolean)
}

export class StableSpeechResult {
  constructor() {
    this.words = []
    this.since = []
    this.committed = []
    this.final = false
    this.conflict = false
  }

  update(text, final, now) {
    const words = speechWords(text)
    let shared = 0
    while (shared < words.length && this.words[shared] === words[shared]) shared += 1
    this.since = words.map((_, i) => i < shared ? this.since[i] : now)
    this.words = words
    this.final = final
    // Played signs cannot be rolled back. Report a correction and quarantine this result.
    if (this.committed.some((word, i) => words[i] !== word)) this.conflict = true
  }

  take(now, forms = []) {
    if (this.conflict) return { correction: true, text: '' }
    const start = this.committed.length
    let end = start
    while (end < this.words.length && (this.final || now - this.since[end] >= (
      end === this.words.length - 1 ? STABLE_TAIL_MS : STABLE_PREFIX_MS
    ))) end += 1
    if (!this.final) {
      // Do not commit "good" out of "good morning", or a supported phrase's prefix,
      // while a following word is still arriving. Bound the lookahead for single words.
      for (let cut = start + 1; cut <= end; cut += 1) {
        const prefix = this.words.slice(start, cut)
        if (forms.some((form) => form.length > prefix.length
          && prefix.every((word, i) => form[i] === word))) {
          const complete = forms.some((form) => form.length > prefix.length && form.length <= end - start
            && form.every((word, i) => this.words[start + i] === word))
          const waitingForTail = forms.some((form) => form.length > prefix.length
            && form.every((word, i) => this.words[start + i] === word))
          if (!complete && (waitingForTail || now - this.since[start] < PHRASE_LOOKAHEAD_MS)) {
            end = start
            break
          }
        }
      }
    }
    if (end === start) return { text: '' }
    const words = this.words.slice(start, end)
    const observedAt = this.since[start]
    this.committed.push(...words)
    return { text: words.join(' '), observedAt, wordCount: words.length, early: !this.final }
  }
}
