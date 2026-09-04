import { Link } from 'react-router-dom'
import Reveal from '../components/Reveal'

const FACTS = [
  { value: '60', unit: 'fps', label: 'playback' },
  { value: '46', unit: 'bones', label: 'driven, fingers included' },
  { value: '0.00', unit: 'mm', label: 'skeleton drift' },
]

export default function Landing() {
  return (
    <div className="landing">
      <section className="landing__hero">
        <Reveal className="landing__hero-copy">
          <h1>Crafting sign language<br />that feels truly human.</h1>
        </Reveal>
        <div className="landing__monogram" aria-hidden="true">S</div>
        <a className="landing__scroll" href="#process">Scroll down ↘</a>
      </section>

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

      <section className="statement">
        <Reveal><h2>We record a movement. We find its meaning. Then we blend every word into one continuous performance. That’s what we do.</h2></Reveal>
        <div className="statement__mark" aria-hidden="true">S</div>
      </section>

      <section className="project project--compact">
        <div className="project__labels"><span>Project No.</span><span>Expertise</span><span>Result</span></div>
        <div className="project__grid">
          <Reveal className="project__number" aria-label="Project two of three"><span>02</span><i /><span>03</span></Reveal>
          <Reveal delay={80} className="project__meta"><ul><li>60 fps</li><li>46 bones</li><li>Velocity matched</li></ul></Reveal>
          <Reveal delay={140} className="project__meta"><p>One expressive<br />digital signer</p></Reveal>
        </div>
        <div className="landing__facts">
          {FACTS.map((fact, index) => (
            <Reveal key={fact.label} delay={index * 70} className="landing__fact">
              <span className="landing__fact-value">{fact.value}<small>{fact.unit}</small></span>
              <span>{fact.label}</span>
            </Reveal>
          ))}
        </div>
        <Reveal className="landing__final">
          <h2>Ready to<br />make language move?</h2>
          <div><Link to="/sign" className="pill-link">Open studio ↗</Link><Link to="/capture" className="pill-link pill-link--outline">Add motion ↗</Link></div>
        </Reveal>
      </section>
    </div>
  )
}
