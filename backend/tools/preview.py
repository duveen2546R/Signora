"""Render a take as a self-contained HTML stick-figure preview.

Lets you confirm a recording parsed correctly - right hand moving, sensible posture, sane timing -
without a Unity build or an avatar. Front and side orthographic views, played back at the recorded
frame rate.

    python tools/preview.py path/to/Hello.csv -o preview.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.ingest import skeleton as sk  # noqa: E402
from app.ingest.rokoko import parse_csv  # noqa: E402

TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>@@TITLE@@ - SignSure preview</title>
<style>
  :root { color-scheme: light dark; --bg:#16161a; --fg:#e8e8ea; --muted:#8a8a95; --accent:#6fc3a8; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.5 system-ui,-apple-system,sans-serif; }
  header { padding:14px 20px; border-bottom:1px solid #2c2c34;
            display:flex; gap:20px; align-items:baseline; flex-wrap:wrap; }
  h1 { font-size:16px; margin:0; }
  .meta { color:var(--muted); font-size:13px; }
  .views { display:flex; gap:16px; padding:16px 20px; flex-wrap:wrap; }
  figure { margin:0; }
  figcaption { color:var(--muted); font-size:12px; text-align:center; padding-top:6px; }
  canvas { background:#0f0f12; border:1px solid #2c2c34; border-radius:8px; }
  .controls { padding:0 20px 20px; display:flex; gap:12px; align-items:center; }
  input[type=range] { flex:1; }
  button { background:var(--accent); border:0; color:#08120f; font:inherit; font-weight:600;
            padding:6px 14px; border-radius:6px; cursor:pointer; }
</style>
<header>
  <h1>@@TITLE@@</h1>
  <span class="meta">@@FRAMES@@ frames &middot; @@FPS@@ fps &middot; @@DURATION@@s
    &middot; dominant hand: @@DOMINANT@@ &middot; travel L @@TRAVEL_L@@cm / R @@TRAVEL_R@@cm</span>
</header>
<div class="views">
  <figure><canvas id="front" width="360" height="460"></canvas>
    <figcaption>Front (looking at the signer)</figcaption></figure>
  <figure><canvas id="side" width="360" height="460"></canvas>
    <figcaption>Side</figcaption></figure>
</div>
<div class="controls">
  <button id="toggle">Pause</button>
  <input id="scrub" type="range" min="0" max="@@LAST@@" value="0" step="1">
  <span class="meta" id="frameLabel">0</span>
</div>
<script>
const DATA = @@DATA@@;
const BONES = @@BONES@@;
const HANDS = @@HANDS@@;
const frames = DATA.length;
let frame = 0, playing = true;

function project(p, view) {
  // Data is Y-up and left-handed with the signer facing +Z. The front view negates X so we are
  // looking AT the signer - their right hand appears on our left, as when watching a person sign.
  return view === 'front' ? [-p[0], p[1]] : [p[2], p[1]];
}

function draw(canvasId, view) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const pts = DATA[frame].map(p => project(p, view));
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 30;
  const scale = Math.min((canvas.width - pad*2) / Math.max(maxX-minX, 0.5),
                         (canvas.height - pad*2) / Math.max(maxY-minY, 0.5));
  const cx = (minX+maxX)/2, cy = (minY+maxY)/2;
  const to = p => [canvas.width/2 + (p[0]-cx)*scale,
                   canvas.height/2 - (p[1]-cy)*scale];

  ctx.lineWidth = 2;
  for (const [a, b, isHand] of BONES) {
    const p = to(pts[a]), q = to(pts[b]);
    ctx.strokeStyle = isHand ? '#6fc3a8' : '#7d7d8c';
    ctx.lineWidth = isHand ? 1.4 : 2.4;
    ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
  }
  ctx.fillStyle = '#e8e8ea';
  for (const h of HANDS) {
    const p = to(pts[h]);
    ctx.beginPath(); ctx.arc(p[0], p[1], 3.5, 0, Math.PI*2); ctx.fill();
  }
}

function render() {
  draw('front', 'front');
  draw('side', 'side');
  document.getElementById('scrub').value = frame;
  document.getElementById('frameLabel').textContent = frame + ' / ' + (frames-1);
}

document.getElementById('scrub').addEventListener('input', e => {
  playing = false;
  document.getElementById('toggle').textContent = 'Play';
  frame = +e.target.value; render();
});

document.getElementById('toggle').addEventListener('click', e => {
  playing = !playing;
  e.target.textContent = playing ? 'Pause' : 'Play';
});

setInterval(() => { if (playing) { frame = (frame + 1) % frames; render(); } }, @@INTERVAL@@);
render();
</script>
"""


def build(take, decimals: int = 4, template: str = TEMPLATE) -> str:
    index = take.segment_index
    hand_segments = {i for seg, i in index.items() if "Digit" in seg or seg.endswith("Hand")}

    bones = []
    for bone in sk.BONES:
        if bone.tail is None:
            continue
        a, b = index[bone.head], index[bone.tail]
        bones.append([a, b, bool(a in hand_segments or b in hand_segments)])

    data = np.round(take.positions, decimals).tolist()
    travel = {
        s: float(np.linalg.norm(np.diff(take.pos(f"{s}Hand"), axis=0), axis=1).sum() * 100)
        for s in ("Left", "Right")
    }

    values = {
        "TITLE": take.name,
        "FRAMES": str(take.frame_count),
        "FPS": f"{take.source_fps:.1f}",
        "DURATION": f"{take.duration:.2f}",
        "DOMINANT": "Right" if travel["Right"] >= travel["Left"] else "Left",
        "TRAVEL_L": f"{travel['Left']:.0f}",
        "TRAVEL_R": f"{travel['Right']:.0f}",
        "LAST": str(take.frame_count - 1),
        "DATA": json.dumps(data),
        "BONES": json.dumps(bones),
        "HANDS": json.dumps(sorted(hand_segments)),
        "INTERVAL": str(int(1000 / max(take.source_fps, 1))),
    }
    # Token substitution rather than str.format: the template is mostly JavaScript, and every brace
    # in it would otherwise need escaping.
    out = template
    for key, value in values.items():
        out = out.replace(f"@@{key}@@", value)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()

    take = parse_csv(args.csv)
    out = args.out or args.csv.with_suffix(".preview.html")
    out.write_text(build(take))
    print(f"{take.name}: {take.frame_count} frames, {take.source_fps:.1f} fps, "
          f"{take.duration:.2f}s -> {out}")


if __name__ == "__main__":
    main()
