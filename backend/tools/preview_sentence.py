"""Render a composed sentence as a stick figure, with the segment boundaries marked.

The numeric tests prove a composed track is geometrically legal - limbs keep their length, seams do
not accelerate harder than the recorded motion. They cannot say whether a transition *looks* like a
person moving. This does, without needing Unity or a browser that will run its render loop.

    python tools/preview_sentence.py THANKYOU FATHER -o sentence.html
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.ingest import landmarks as lm  # noqa: E402
from app.ingest.compose import compose, prepare  # noqa: E402
from app.ingest.landmarks import LandmarkSkeleton, to_landmarks  # noqa: E402
from app.ingest.rokoko import parse_csv  # noqa: E402

EXPORTS = os.path.expanduser(
    "~/Library/Application Support/com.RokokoElectronics.RokokoStudio/Exports"
)

# Drawn in pose-landmark space. Hands are appended per frame after the 33 pose points.
POSE_EDGES = [(11, 12), (11, 23), (12, 24), (23, 24), (11, 13), (13, 15), (12, 14), (14, 16)]
HEAD_EDGES = [(7, 8), (0, 7), (0, 8)]

TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>@@TITLE@@ - SignSure sentence</title>
<style>
  :root { color-scheme: dark; --bg:#141418; --fg:#e9e9ec; --muted:#8b8b96;
          --sign:#6fc3a8; --transition:#d98f4f; --hold:#7a7a88; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.5 system-ui,-apple-system,sans-serif; }
  header { padding:14px 20px; border-bottom:1px solid #2a2a32; }
  h1 { font-size:16px; margin:0 0 4px; }
  .meta { color:var(--muted); font-size:13px; }
  .views { display:flex; gap:16px; padding:16px 20px; flex-wrap:wrap; }
  figure { margin:0; }
  figcaption { color:var(--muted); font-size:12px; text-align:center; padding-top:6px; }
  canvas { background:#0e0e11; border:1px solid #2a2a32; border-radius:8px; }
  .controls { padding:0 20px 8px; display:flex; gap:12px; align-items:center; }
  input[type=range] { flex:1; }
  button { background:var(--sign); border:0; color:#08120f; font:inherit; font-weight:600;
           padding:6px 14px; border-radius:6px; cursor:pointer; }
  .timeline { display:flex; height:26px; margin:0 20px 18px; border-radius:6px; overflow:hidden;
              border:1px solid #2a2a32; }
  .timeline div { display:flex; align-items:center; justify-content:center; font-size:11px;
                  color:#0e0e11; font-weight:700; overflow:hidden; white-space:nowrap; }
  .now { color:var(--muted); font-variant-numeric:tabular-nums; }
  .quality { margin:0 20px 20px; padding:12px; background:#0e0e11; border:1px solid #2a2a32;
             border-radius:8px; font:12px/1.5 ui-monospace,SFMono-Regular,monospace; white-space:pre-wrap; }
</style>
<header>
  <h1>@@TITLE@@</h1>
  <div class="meta">@@FRAMES@@ frames &middot; @@FPS@@ fps &middot; @@DURATION@@s &middot;
    green = sign, orange = generated transition, grey = coast to rest</div>
</header>
<div class="views">
  <figure><canvas id="front" width="380" height="470"></canvas>
    <figcaption>Front (facing the signer)</figcaption></figure>
  <figure><canvas id="side" width="380" height="470"></canvas>
    <figcaption>Side</figcaption></figure>
  <figure><canvas id="speed" width="380" height="470"></canvas>
    <figcaption>Wrist speed (cm/s): left grey, right green</figcaption></figure>
  <figure><canvas id="accel" width="380" height="470"></canvas>
    <figcaption>Wrist acceleration magnitude (cm/s²)</figcaption></figure>
  <figure><canvas id="jerk" width="380" height="470"></canvas>
    <figcaption>Wrist jerk magnitude (cm/s³)</figcaption></figure>
</div>
<div class="controls">
  <button id="toggle">Pause</button>
  <label>Speed <select id="rate"><option value="0.5">0.5×</option><option value="1" selected>1×</option></select></label>
  <input id="scrub" type="range" min="0" max="@@LAST@@" value="0" step="1">
  <span class="now" id="label">0</span>
</div>
<div class="timeline" id="timeline"></div>
<pre class="quality" id="quality"></pre>
<script>
const FRAMES = @@DATA@@;
const EDGES = @@EDGES@@;
const SEGMENTS = @@SEGMENTS@@;
const SPEED = @@SPEED@@;
const ACCEL = @@ACCEL@@;
const JERK = @@JERK@@;
const QUALITY = @@QUALITY@@;
const FPS = @@FPSNUM@@;
let frame = 0, playhead = 0, rate = 1, playing = true;

const colours = {sign:'#6fc3a8', transition:'#d98f4f', hold:'#7a7a88'};
const bar = document.getElementById('timeline');
for (const s of SEGMENTS) {
  const d = document.createElement('div');
  d.style.flex = String(s.endFrame - s.startFrame);
  d.style.background = colours[s.kind] || '#555';
  d.textContent = s.gloss || s.kind;
  d.title = `${s.kind} ${s.startFrame}..${s.endFrame}`;
  bar.appendChild(d);
}

function project(p, view) {
  return view === 'front' ? [-p[0], p[1]] : [p[2], p[1]];
}

function draw(id, view) {
  const c = document.getElementById(id), ctx = c.getContext('2d');
  ctx.clearRect(0, 0, c.width, c.height);
  const pts = FRAMES[frame].map(p => project(p, view));
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const pad = 34;
  const scale = Math.min((c.width - pad*2) / Math.max(Math.max(...xs)-Math.min(...xs), 0.6),
                         (c.height - pad*2) / Math.max(Math.max(...ys)-Math.min(...ys), 0.9));
  const cx = (Math.max(...xs)+Math.min(...xs))/2, cy = (Math.max(...ys)+Math.min(...ys))/2;
  const to = p => [c.width/2 + (p[0]-cx)*scale, c.height/2 - (p[1]-cy)*scale];
  for (const [a, b, hand] of EDGES) {
    const p = to(pts[a]), q = to(pts[b]);
    ctx.strokeStyle = hand ? '#6fc3a8' : '#8e8e9c';
    ctx.lineWidth = hand ? 1.3 : 2.6;
    ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
  }
}

function drawMetric(id, values, unit) {
  const c = document.getElementById(id), ctx = c.getContext('2d');
  ctx.clearRect(0, 0, c.width, c.height);
  const max = Math.max(...values.left, ...values.right, 1), pad = 20;
  let x0 = 0;
  for (const s of SEGMENTS) {
    const w = (s.endFrame - s.startFrame) / FRAMES.length * (c.width - pad*2);
    ctx.fillStyle = (colours[s.kind] || '#555') + '22';
    ctx.fillRect(pad + x0, pad, w, c.height - pad*2);
    x0 += w;
  }
  for (const [side, colour] of [['left', '#e9e9ec'], ['right', '#6fc3a8']]) {
    ctx.strokeStyle = colour; ctx.lineWidth = 1.4; ctx.beginPath();
    values[side].forEach((v, i) => {
      const x = pad + i / Math.max(values[side].length, 1) * (c.width - pad*2);
      const y = c.height - pad - v / max * (c.height - pad*2);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  }
  const x = pad + frame / FRAMES.length * (c.width - pad*2);
  ctx.strokeStyle = '#d98f4f'; ctx.beginPath(); ctx.moveTo(x, pad); ctx.lineTo(x, c.height-pad); ctx.stroke();
  ctx.fillStyle = '#8b8b96'; ctx.font = '11px system-ui';
  ctx.fillText(max.toFixed(0) + ' ' + unit, pad, pad - 6);
}

function render() {
  draw('front', 'front'); draw('side', 'side');
  drawMetric('speed', SPEED, 'cm/s');
  drawMetric('accel', ACCEL, 'cm/s²');
  drawMetric('jerk', JERK, 'cm/s³');
  document.getElementById('scrub').value = frame;
  const seg = SEGMENTS.find(s => frame >= s.startFrame && frame < s.endFrame);
  document.getElementById('label').textContent =
    `${frame} / ${FRAMES.length-1}  ${seg ? seg.kind + (seg.gloss ? ' ' + seg.gloss : '') : ''}`;
}

document.getElementById('scrub').addEventListener('input', e => {
  playing = false; document.getElementById('toggle').textContent = 'Play';
  frame = +e.target.value; playhead = frame; render();
});
document.getElementById('toggle').addEventListener('click', e => {
  playing = !playing; e.target.textContent = playing ? 'Pause' : 'Play';
});
document.getElementById('rate').addEventListener('change', e => { rate = +e.target.value; });
setInterval(() => {
  if (playing) {
    playhead = (playhead + rate) % FRAMES.length;
    frame = Math.floor(playhead);
    render();
  }
}, 1000/FPS);
render();
document.getElementById('quality').textContent = [
  `Blend ${QUALITY.status} · score ${QUALITY.score} · algorithm v${QUALITY.algorithmVersion}`,
  ...QUALITY.seams.map(s => {
    const contacts = Object.entries(s.contacts || {}).flatMap(([edge, value]) =>
      Object.entries(value).filter(([, active]) => active).map(([kind]) => `${edge}:${kind}`));
    return `${s.fromGloss || 'neutral'} -> ${s.toGloss || 'neutral'}  ${s.mode}  ` +
      `${s.fromFrame}->${s.toFrame}  ${s.durationMs}ms  score ${s.score}` +
      (contacts.length ? `  contacts ${contacts.join(',')}` : '') +
      (s.reasons?.length ? `  ${s.reasons.join('; ')}` : '');
  }),
].join('\n');
</script>
"""


def build_edges() -> list[list]:
    edges = [[a, b, False] for a, b in POSE_EDGES + HEAD_EDGES]
    for offset in (lm.POSE_LANDMARK_COUNT, lm.POSE_LANDMARK_COUNT + lm.HAND_LANDMARK_COUNT):
        for a, b in lm.HAND_SPOKES + lm.HAND_BONES:
            edges.append([offset + a, offset + b, True])
    return edges


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("glosses", nargs="+", help="take names, e.g. ThankYou Father")
    ap.add_argument("-o", "--out", type=Path, default=Path("sentence.html"))
    args = ap.parse_args()

    available = {os.path.basename(p)[:-4].lower(): p for p in sorted(glob.glob(f"{EXPORTS}/*.csv"))}
    chosen = []
    for name in args.glosses:
        path = available.get(name.lower())
        if path is None:
            raise SystemExit(f"no recording named {name!r}; have: {', '.join(sorted(available))}")
        chosen.append((name.upper(), to_landmarks(parse_csv(path))))

    skeleton = LandmarkSkeleton.from_takes([t for _, t in chosen])
    prepared = [(g, prepare(t, skeleton)) for g, t in chosen]
    result = compose(skeleton, prepared)
    track = result.track

    frames = np.concatenate([track.pose, track.left_hand, track.right_hand], axis=1)
    velocity = {
        side: np.diff(track.pose[:, wrist], axis=0) * track.fps * 100.0
        for side, wrist in (("left", 15), ("right", 16))
    }
    speed = {side: np.linalg.norm(values, axis=1) for side, values in velocity.items()}
    acceleration_vectors = {
        side: np.diff(values, axis=0) * track.fps for side, values in velocity.items()
    }
    acceleration = {
        side: np.linalg.norm(values, axis=1) for side, values in acceleration_vectors.items()
    }
    jerk = {
        side: np.linalg.norm(np.diff(values, axis=0), axis=1) * track.fps
        for side, values in acceleration_vectors.items()
    }

    values = {
        "TITLE": " + ".join(g for g, _ in chosen),
        "FRAMES": str(track.frame_count),
        "FPS": f"{track.fps:.0f}",
        "FPSNUM": f"{track.fps:.0f}",
        "DURATION": f"{track.duration:.2f}",
        "LAST": str(track.frame_count - 1),
        "DATA": json.dumps(np.round(frames, 4).tolist()),
        "EDGES": json.dumps(build_edges()),
        "SEGMENTS": json.dumps([s.as_dict() for s in result.segments]),
        "SPEED": json.dumps({side: np.round(values, 1).tolist() for side, values in speed.items()}),
        "ACCEL": json.dumps({side: np.round(values, 1).tolist()
                             for side, values in acceleration.items()}),
        "JERK": json.dumps({side: np.round(values, 1).tolist() for side, values in jerk.items()}),
        "QUALITY": json.dumps(result.blend_quality),
    }
    out = TEMPLATE
    for key, value in values.items():
        out = out.replace(f"@@{key}@@", value)
    args.out.write_text(out)

    print(f"{track.frame_count} frames ({track.duration:.2f}s) -> {args.out}")
    for s in result.segments:
        print(f"  {s.kind:11s} {s.gloss:14s} {s.start:4d}..{s.end:4d}"
              f"  {(s.end - s.start) / track.fps:5.2f}s")


if __name__ == "__main__":
    main()
