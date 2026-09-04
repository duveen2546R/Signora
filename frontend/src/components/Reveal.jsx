import { useEffect, useRef, useState } from 'react'

// However the reveal is triggered, the content appears within this long. Nothing readable may
// depend on an observer callback arriving: a backgrounded tab, a browser that throttles
// compositing, or an environment where IntersectionObserver simply never fires would otherwise
// leave the page permanently blank.
const SAFETY_MS = 900

/**
 * Fades and lifts its children into place once, when they first reach the viewport.
 *
 * The reference site animates almost everything on a one-second expo curve; this is that motion
 * applied to page content, so arriving at a section feels continuous with hovering a link. The
 * hidden start state is applied by CSS only once JavaScript has marked the document, so without
 * scripting the content is simply there.
 */
export default function Reveal({ as: Tag = 'div', delay = 0, className = '', children, ...rest }) {
  const ref = useRef(null)
  const [shown, setShown] = useState(false)

  useEffect(() => {
    const node = ref.current
    let observer

    const safety = setTimeout(() => setShown(true), SAFETY_MS + delay)

    if (node && typeof IntersectionObserver === 'function') {
      observer = new IntersectionObserver(
        ([entry]) => {
          if (!entry.isIntersecting) return
          setShown(true)
          observer.disconnect()
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
  }, [delay])

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
