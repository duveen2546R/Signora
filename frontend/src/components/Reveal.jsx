import { useEffect, useRef, useState } from 'react'

// However the reveal is triggered, the content appears within this long. Nothing readable may
// depend on an observer callback arriving: a backgrounded tab, a browser that throttles
// compositing, or an environment where IntersectionObserver simply never fires would otherwise
// leave the page permanently blank.
const SAFETY_MS = 900

/**
 * Lifts its children out of depth — a slight rotation on the X axis, a push back along Z and a
 * short blur resolving into place — as they reach the viewport.
 *
 * The animation replays every time the element enters view, in either scroll direction, so a
 * visitor coming back up the page sees the same motion rather than a static block. Pass
 * `once` to freeze an element after its first reveal. The hidden start state is applied by CSS
 * only once JavaScript has marked the document, so without scripting the content is simply there.
 */
export default function Reveal({ as: Tag = 'div', delay = 0, once = false, className = '', children, ...rest }) {
  const ref = useRef(null)
  const [shown, setShown] = useState(false)

  useEffect(() => {
    const node = ref.current
    let observer

    const safety = setTimeout(() => setShown(true), SAFETY_MS + delay)

    if (node && typeof IntersectionObserver === 'function') {
      observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) {
            clearTimeout(safety)
            setShown(true)
            if (once) observer.disconnect()
          } else if (!once) {
            // Re-arm only once the element is fully clear of the viewport, so an element that is
            // merely clipped at an edge does not flicker while the reader scrolls past it.
            setShown(false)
          }
        },
        { threshold: 0.08, rootMargin: '0px 0px -40px' },
      )
      observer.observe(node)
    } else {
      setShown(true)
    }

    return () => {
      clearTimeout(safety)
      observer?.disconnect()
    }
  }, [delay, once])

  return (
    <Tag
      ref={ref}
      className={`reveal ${shown ? 'reveal--in' : ''} ${className}`.trim()}
      style={{ '--reveal-delay': `${delay}ms` }}
      {...rest}
    >
      {children}
    </Tag>
  )
}
