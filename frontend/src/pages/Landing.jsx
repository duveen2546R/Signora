import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Reveal from '../components/Reveal'

const FACTS = [
  { value: 60, unit: 'fps', label: 'playback' },
  { value: 46, unit: 'bones', label: 'driven, fingers included' },
  { value: 12, unit: 'ms', label: 'blend seam tolerance' },
]

const PIPELINE = [
  { step: '01', title: 'Capture', copy: 'A deaf signer performs the word in a Rokoko Smartsuit and Smartgloves. Every joint, down to the distal finger bones, is recorded at 60 fps.' },
  { step: '02', title: 'Segment', copy: 'Each take is split into start, sign and end phases so the meaningful movement can be lifted away from the signer walking into frame.' },
  { step: '03', title: 'Translate', copy: 'English is parsed into Indian Sign Language gloss order. Words with no recorded sign are fingerspelled rather than dropped.' },
  { step: '04', title: 'Blend', copy: 'Signs are joined on matched velocity, so the hands travel between words instead of snapping. The result is one continuous performance.' },
]

const CAPABILITIES = [
  { title: 'Real motion, not keyframes', copy: 'Nothing in the library is hand-animated. Every sign is a recording of a person signing it.' },
  { title: 'Fingerspelling fallback', copy: 'An unknown name still gets signed, letter by letter, instead of vanishing from the sentence.' },
  { title: 'Phase-aware editing', copy: 'Reviewers can move a phase boundary by a single frame and see the skeleton respond immediately.' },
  { title: 'Velocity-matched seams', copy: 'Transitions are chosen where the hands are already moving in a compatible direction.' },
  { title: 'Zero skeleton drift', copy: 'Retargeting keeps bone lengths fixed, so long sentences never distort the avatar.' },
  { title: 'Growing library', copy: 'New captures are ingested, reviewed and published without touching the renderer.' },
]

const MARQUEE = ['motion capture', 'indian sign language', '60 fps', 'rokoko smartgloves', 'velocity blending', 'fingerspelling', 'phase review', 'retargeting']

/** Counts up to a number once the element is on screen; the value is readable before it animates. */
function useCountUp(target, run) {
  const [value, setValue] = useState(target)
  useEffect(() => {
    if (!run) return undefined
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return undefined
    let frame
    const started = performance.now()
    const tick = (now) => {
      const progress = Math.min((now - started) / 1200, 1)
      setValue(Math.round(target * (1 - (1 - progress) ** 3)))
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    // The first frame writes 0 itself, so the effect body stays free of synchronous state writes.
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, run])
  return value
}

function Fact({ fact, delay }) {
  const ref = useRef(null)
  const [seen, setSeen] = useState(false)
  const value = useCountUp(fact.value, seen)

  useEffect(() => {
    const node = ref.current
    if (!node || typeof IntersectionObserver !== 'function') return setSeen(true)
    // Re-arms on exit so the count runs again when the reader scrolls back to it.
    const observer = new IntersectionObserver(([entry]) => setSeen(entry.isIntersecting), { threshold: 0.4 })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return (
    <Reveal delay={delay} className="landing__fact">
      <span className="landing__fact-value" ref={ref}>{value}<small>{fact.unit}</small></span>
      <span>{fact.label}</span>
    </Reveal>
  )
}

export default function Landing() {
  return (
    <div className="landing">
      <section className="landing__hero">
        <Reveal className="landing__hero-copy">
          <span className="landing__hero-eyebrow">Indian Sign Language · motion captured</span>
          <h1>Crafting sign language<br />that feels truly human.</h1>
          <p className="landing__hero-lede">
            SignSure turns written English into a signed performance driven by real motion capture —
            the timing, the handshape and the intention of a human signer, preserved end to end.
          </p>
          <div className="landing__hero-actions">
            <Link to="/sign" className="pill-link">Open studio <span aria-hidden="true">↗</span></Link>
            <Link to="/capture" className="pill-link pill-link--outline">Browse the library ↗</Link>
          </div>
        </Reveal>
        <div className="landing__monogram" aria-hidden="true">S</div>
        <a className="landing__scroll" href="#process">Scroll down ↘</a>
      </section>

      <div className="marquee" aria-hidden="true">
        <div className="marquee__track">
          {[0, 1].map((copy) => (
            <span key={copy}>
              {MARQUEE.map((word) => <i key={word}>{word}<b>·</b></i>)}
            </span>
          ))}
        </div>
      </div>

      <section className="project" id="process">
        <div className="project__labels">
          <span>Project No.</span><span>Expertise</span><span>Outcome</span>
        </div>
        <div className="project__grid">
          <Reveal className="project__number" aria-label="Project one of three">
            <span>01</span><i /><span>03</span>
          </Reveal>
          <Reveal delay={100} className="project__meta">
            <ul><li>Motion capture</li><li>Translation</li><li>Development</li><li>AI</li></ul>
          </Reveal>
          <Reveal delay={160} className="project__meta"><p>Natural, continuous<br />sign performance</p></Reveal>
        </div>
        <div className="project__feature">
          <Reveal className="studio-preview" aria-label="Preview of the SignSure studio">
            <div className="studio-preview__bar"><span /><span /><span /><b>signsure studio</b></div>
            <div className="studio-preview__body">
              <p>GOOD<br />MORNING</p>
              <div className="studio-preview__avatar" aria-hidden="true"><span /><i /><b /></div>
              <small>motion-captured Indian Sign Language</small>
            </div>
          </Reveal>
          <Reveal delay={100} className="project__story">
            <h2>Type it.<br />Watch it signed.</h2>
            <div className="project__story-copy"><span>Info</span><p>SignSure transforms written English into sign language performed by an avatar driven by real motion capture. Every word carries the timing, shape and intention of a human signer.</p></div>
            <Link to="/sign" className="pill-link">Open studio <span aria-hidden="true">↗</span></Link>
          </Reveal>
        </div>
      </section>

      <section className="pipeline" id="technology">
        <Reveal className="pipeline__head">
          <span className="eyebrow">How it works</span>
          <h2>Four steps between a<br />recorded gesture and a sentence.</h2>
        </Reveal>
        <ol className="pipeline__list">
          {PIPELINE.map((stage, index) => (
            <Reveal as="li" key={stage.step} delay={index * 90} className="pipeline__item">
              <span className="pipeline__step">{stage.step}</span>
              <h3>{stage.title}</h3>
              <p>{stage.copy}</p>
            </Reveal>
          ))}
        </ol>
      </section>

      <section className="statement">
        <Reveal><h2>We record a movement. We find its meaning. Then we blend every word into one continuous performance. That’s what we do.</h2></Reveal>
        <div className="statement__mark" aria-hidden="true">S</div>
      </section>

      <section className="capabilities" id="about">
        <Reveal className="capabilities__head">
          <span className="eyebrow">What it does</span>
          <h2>Built for the parts of<br />signing that usually get lost.</h2>
        </Reveal>
        <div className="capabilities__grid">
          {CAPABILITIES.map((item, index) => (
            <Reveal key={item.title} delay={(index % 3) * 80} className="capability">
              <h3>{item.title}</h3>
              <p>{item.copy}</p>
              <span className="capability__rule" aria-hidden="true" />
            </Reveal>
          ))}
        </div>
      </section>

      <section className="project project--compact">
        <div className="project__labels"><span>Project No.</span><span>Expertise</span><span>Result</span></div>
        <div className="project__grid">
          <Reveal className="project__number" aria-label="Project two of three"><span>02</span><i /><span>03</span></Reveal>
          <Reveal delay={80} className="project__meta"><ul><li>60 fps</li><li>46 bones</li><li>Velocity matched</li></ul></Reveal>
          <Reveal delay={140} className="project__meta"><p>One expressive<br />digital signer</p></Reveal>
        </div>
        <div className="landing__facts">
          {FACTS.map((fact, index) => <Fact key={fact.label} fact={fact} delay={index * 70} />)}
        </div>
        <Reveal className="landing__final">
          <h2>Ready to<br />make language move?</h2>
          <div><Link to="/sign" className="pill-link">Open studio ↗</Link><Link to="/capture" className="pill-link pill-link--outline">Add motion ↗</Link></div>
        </Reveal>
      </section>
    </div>
  )
}
