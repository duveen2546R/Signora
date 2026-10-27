/**
 * Bottom-right overlay panel.
 *
 * Built inside a shadow root so YouTube's stylesheet cannot reach in and the panel's styles
 * cannot leak out. Positioned above YouTube's control bar and sized so it never covers the
 * progress bar or the right-hand control cluster; `pointer-events` is enabled only on the panel
 * itself, so clicks anywhere else still reach the page.
 */

const STATUS_TEXT = {
  idle: 'Idle',
  'checking-backend': 'Checking Signora backend…',
  'backend-unavailable': 'Signora backend unavailable',
  'preparing-captions': 'Preparing captions…',
  'no-captions': 'No English captions available',
  'preparing-plan': 'Preparing sign plan…',
  'plan-failed': 'Sign plan failed',
  ready: 'Ready — press play',
  signing: 'Signing',
  paused: 'Paused',
  'catch-up': 'Video paused while the sign finishes',
  'buffering-signs': 'Buffering next signs…',
  ended: 'Finished',
}

const STATUS_KIND = {
  'backend-unavailable': 'bad',
  'no-captions': 'bad',
  'plan-failed': 'bad',
  'catch-up': 'warn',
  'buffering-signs': 'warn',
  paused: 'warn',
  signing: 'good',
  ready: 'good',
}

export class Overlay {
  constructor({ onRetry, onPickSubtitle, onDownloadCaptions, onToggleEnabled } = {}) {
    this.onRetry = onRetry
    this.onPickSubtitle = onPickSubtitle
    this.onDownloadCaptions = onDownloadCaptions
    this.onToggleEnabled = onToggleEnabled
    this.host = null
    this.root = null
    this.expanded = true
    this.state = {
      status: 'idle', detail: '', caption: '', glosses: [], activeGloss: null,
      progress: 0, rate: 1, coverage: null, unsupported: [], avatarMount: null,
    }
  }

  mount(expanded = true) {
    if (this.host) return this
    this.expanded = expanded
    const host = document.createElement('div')
    host.id = 'signora-overlay-host'
    // A high stacking context, but still beneath YouTube's own modals/menus.
    Object.assign(host.style, {
      position: 'fixed', right: '16px', bottom: '16px', zIndex: '2147483000',
      width: '440px', maxWidth: 'calc(100vw - 32px)', pointerEvents: 'none',
    })
    this.host = host
    this.root = host.attachShadow({ mode: 'open' })
    this.root.innerHTML = `
      <style>
        :host { all: initial; }
        * { box-sizing: border-box; font-family: "Roboto", system-ui, -apple-system, sans-serif; }
        .panel {
          pointer-events: auto;
          background: rgba(15, 15, 17, 0.94);
          color: #f4f4f5;
          border: 1px solid rgba(255,255,255,0.14);
          border-radius: 12px;
          box-shadow: 0 10px 34px rgba(0,0,0,0.5);
          backdrop-filter: blur(8px);
          overflow: hidden;
          font-size: 13px;
          line-height: 1.45;
        }
        .head {
          display: flex; align-items: center; gap: 8px;
          padding: 9px 11px; cursor: pointer; user-select: none;
          background: rgba(255,255,255,0.045);
          border-bottom: 1px solid rgba(255,255,255,0.09);
        }
        .mark { font-weight: 700; letter-spacing: .06em; font-size: 11px; text-transform: uppercase; color: #a5b4fc; }
        .dot { width: 8px; height: 8px; border-radius: 50%; background: #71717a; flex: 0 0 auto; }
        .dot.good { background: #22c55e; } .dot.warn { background: #f59e0b; } .dot.bad { background: #ef4444; }
        .dot.busy { background: #3b82f6; animation: pulse 1.1s ease-in-out infinite; }
        @keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
        .status { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
        .chev { font-size: 11px; opacity: .65; }
        .body { padding: 10px 11px 12px; display: grid; gap: 9px; }
        .body[hidden] { display: none; }
        .label { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: #a1a1aa; margin-bottom: 2px; }
        .caption { font-size: 13px; color: #fafafa; max-height: 54px; overflow: auto; }
        .muted { color: #a1a1aa; font-style: italic; }
        .glosses { display: flex; flex-wrap: wrap; gap: 4px; }
        .gloss {
          font-size: 11px; font-weight: 600; letter-spacing: .03em;
          padding: 2px 7px; border-radius: 999px;
          background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12); color: #d4d4d8;
        }
        .gloss.active { background: #4f46e5; border-color: #6366f1; color: #fff; }
        .bar { height: 4px; border-radius: 999px; background: rgba(255,255,255,0.12); overflow: hidden; }
        .bar > i { display: block; height: 100%; background: linear-gradient(90deg,#6366f1,#22d3ee); transition: width .1s linear; }
        .meta { display: flex; gap: 10px; flex-wrap: wrap; font-size: 11px; color: #a1a1aa; }
        .meta b { color: #e4e4e7; font-weight: 600; }
        .detail { font-size: 11.5px; color: #fca5a5; }
        .warnrow { font-size: 11.5px; color: #fcd34d; }
        .avatar {
          width: 100%; height: min(52vh, 520px); min-height: 360px; border-radius: 8px; overflow: hidden;
          background: #000; border: 1px solid rgba(255,255,255,0.1);
          display: grid; place-items: center; position: relative;
        }
        .mockglyph { font-size: 26px; font-weight: 800; letter-spacing: .05em; color: #fff; text-align: center; padding: 0 8px; }
        .mocknote { position: absolute; top: 5px; left: 7px; font-size: 9px; text-transform: uppercase;
                    letter-spacing: .08em; color: #a5b4fc; background: rgba(0,0,0,.45); padding: 1px 5px; border-radius: 4px; }
        .actions { display: flex; gap: 6px; flex-wrap: wrap; }
        button {
          font: inherit; font-size: 11.5px; font-weight: 600; color: #e4e4e7;
          background: rgba(255,255,255,0.09); border: 1px solid rgba(255,255,255,0.16);
          border-radius: 7px; padding: 5px 9px; cursor: pointer;
        }
        button:hover { background: rgba(255,255,255,0.16); }
        button.primary { background: #4f46e5; border-color: #6366f1; color: #fff; }
      </style>
      <div class="panel">
        <div class="head" part="head">
          <span class="dot" id="dot"></span>
          <span class="mark">Signora</span>
          <span class="status" id="status">Idle</span>
          <span class="chev" id="chev">▾</span>
        </div>
        <div class="body" id="body">
          <div class="avatar" id="avatar"></div>
          <div>
            <div class="label">Current caption</div>
            <div class="caption" id="caption"><span class="muted">—</span></div>
          </div>
          <div>
            <div class="label">Signs</div>
            <div class="glosses" id="glosses"><span class="muted">—</span></div>
          </div>
          <div class="bar"><i id="bar" style="width:0%"></i></div>
          <div class="meta" id="meta"></div>
          <div class="warnrow" id="warn" hidden></div>
          <div class="detail" id="detail" hidden></div>
          <div class="actions">
            <button id="retry" class="primary">Retry</button>
            <button id="pick">Load subtitle file…</button>
            <button id="download">Download captions</button>
          </div>
        </div>
      </div>
    `
    const $ = (id) => this.root.getElementById(id)
    this.el = {
      dot: $('dot'), status: $('status'), chev: $('chev'), body: $('body'),
      caption: $('caption'), glosses: $('glosses'), bar: $('bar'), meta: $('meta'),
      warn: $('warn'), detail: $('detail'), avatar: $('avatar'),
      retry: $('retry'), pick: $('pick'), download: $('download'),
    }
    $('status').parentElement.addEventListener('click', () => this.toggle())
    this.el.retry.addEventListener('click', (e) => { e.stopPropagation(); this.onRetry?.() })
    this.el.pick.addEventListener('click', (e) => { e.stopPropagation(); this.onPickSubtitle?.() })
    this.el.download.addEventListener('click', (e) => { e.stopPropagation(); this.onDownloadCaptions?.() })

    document.documentElement.appendChild(host)
    this.el.body.hidden = !this.expanded
    this.el.chev.textContent = this.expanded ? '▾' : '▸'
    return this
  }

  /** Where an avatar adapter may mount its own view (the Unity iframe). */
  avatarMount() {
    return this.el?.avatar ?? null
  }

  toggle() {
    this.expanded = !this.expanded
    this.el.body.hidden = !this.expanded
    this.el.chev.textContent = this.expanded ? '▾' : '▸'
  }

  update(patch) {
    Object.assign(this.state, patch)
    this.render()
  }

  render() {
    if (!this.el) return
    const s = this.state

    const busy = ['checking-backend', 'preparing-captions', 'preparing-plan'].includes(s.status)
    this.el.dot.className = `dot ${busy ? 'busy' : (STATUS_KIND[s.status] || '')}`
    this.el.status.textContent = STATUS_TEXT[s.status] || s.status

    this.el.caption.innerHTML = ''
    if (s.caption) this.el.caption.textContent = s.caption
    else this.el.caption.innerHTML = '<span class="muted">—</span>'

    this.el.glosses.innerHTML = ''
    if (s.glosses?.length) {
      s.glosses.forEach((gloss, index) => {
        const chip = document.createElement('span')
        // Match on position as well as name so a repeated word highlights the right occurrence.
        const active = s.activeGloss !== null
          && gloss === s.activeGloss
          && (s.activeIndex === undefined || s.activeIndex === null || s.activeIndex === index)
        chip.className = `gloss${active ? ' active' : ''}`
        chip.textContent = gloss
        this.el.glosses.appendChild(chip)
      })
    } else {
      this.el.glosses.innerHTML = '<span class="muted">—</span>'
    }

    this.el.bar.style.width = `${Math.round((s.progress || 0) * 100)}%`

    const bits = [`<span>Speed <b>${Number(s.rate || 1).toFixed(2)}×</b></span>`]
    if (s.coverage) {
      bits.push(`<span>Coverage <b>${s.coverage.percent}%</b></span>`)
      bits.push(`<span>Units <b>${s.coverage.signedUnits}/${s.coverage.totalUnits}</b></span>`)
    }
    if (s.adapterName) bits.push(`<span>Avatar <b>${s.adapterName}</b></span>`)
    this.el.meta.innerHTML = bits.join('')

    const unsupported = s.unsupported || []
    this.el.warn.hidden = unsupported.length === 0
    if (unsupported.length) {
      this.el.warn.textContent = `No sign for: ${unsupported.slice(0, 12).join(', ')}`
        + (unsupported.length > 12 ? ` (+${unsupported.length - 12} more)` : '')
    }

    this.el.detail.hidden = !s.detail
    if (s.detail) this.el.detail.textContent = s.detail
  }

  /** Mock-adapter view: show the sign being performed. */
  renderMock({ activeGloss, playing, paused }) {
    if (!this.el) return
    const mount = this.el.avatar
    if (mount.firstElementChild?.tagName === 'IFRAME') return // Unity owns the view
    mount.innerHTML = `
      <span class="mocknote">mock avatar</span>
      <span class="mockglyph">${activeGloss ? activeGloss.replace(/_/g, ' ')
        : (playing ? (paused ? '⏸' : '…') : '🧍')}</span>
    `
  }

  destroy() {
    this.host?.remove()
    this.host = null
    this.el = null
  }
}
