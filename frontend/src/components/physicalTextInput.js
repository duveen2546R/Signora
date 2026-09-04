/**
 * Apply a printable/delete key to a text selection.
 *
 * Unity WebGL builds can prevent the browser's native editing default even when an HTML input
 * owns focus. Returning null lets callers leave shortcuts, IME input, and navigation keys alone.
 */
export function applyPhysicalTextKey(text, key, selectionStart, selectionEnd) {
  const start = Math.max(0, Math.min(text.length, selectionStart ?? text.length))
  const end = Math.max(start, Math.min(text.length, selectionEnd ?? start))

  if (key === 'Backspace') {
    const deleteFrom = start === end ? Math.max(0, start - 1) : start
    return {
      text: text.slice(0, deleteFrom) + text.slice(end),
      caret: deleteFrom,
    }
  }

  if (key === 'Delete') {
    const deleteTo = start === end ? Math.min(text.length, end + 1) : end
    return {
      text: text.slice(0, start) + text.slice(deleteTo),
      caret: start,
    }
  }

  if (key.length !== 1) return null
  return {
    text: text.slice(0, start) + key + text.slice(end),
    caret: start + key.length,
  }
}
