"""Operating characteristics of the conditional single-take protocol against known truth.

Writes one JSON line per simulated take and angle; summarise with --summary.
    python tools/simulate_conditional_equivalence.py --noise-px 2 --seeds 60 --output sims.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.validation.conditional_equivalence import evaluate_conditional  # noqa: E402
from app.validation.equivalence_single_take import EQUIVALENT, load_margins  # noqa: E402
from app.validation.fbx_motion import load_motion  # noqa: E402
from app.validation.multiview import sign_window  # noqa: E402
from app.validation.single_take_simulation import Scenario, padded, simulate  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def scenarios(motion, base: Scenario, margin: float):
    start, stop = sign_window(padded(motion, base.hold_s))
    frames = len(padded(motion, base.hold_s).times)
    sine = np.zeros(frames)
    sine[start:stop] = margin * np.sqrt(2) * np.sin(2 * np.pi * np.arange(stop - start) / (stop - start))
    # Errors start at sign onset: a constant error that also covers the pre-sign hold is, correctly,
    # absorbed by the pre-registered static-offset rule and would test nothing.
    const = np.zeros(frames)
    const[start:] = margin
    noisy = replace(base, motion_noise_factor=1.5)
    return {
        "null": (base, None),
        "const+margin": (base, {"right": const}),
        "sine rms=margin": (base, {"right": sine}),
        "null, motion noise 1.5x": (noisy, None),
        "const+margin, motion noise 1.5x": (noisy, {"right": const}),
    }


def run(noise_px: float, seeds: int, output: Path, draws: int, refits: int, only: str | None = None) -> None:
    warnings.simplefilter("ignore")
    motion = load_motion(ROOT / "MotionCaptureFbx/action.fbx", include_elbows=True)
    margins = load_margins()
    base = replace(Scenario(), noise_px=noise_px, joint_offset_m=0.0, hold_s=1.0)
    with output.open("a") as stream:
        for label, (scenario, injected) in scenarios(motion, base, margins["right_elbow_flexion"]).items():
            if only and label != only:
                continue
            for seed in range(seeds):
                sim = simulate(motion, scenario, injected=injected, replicates=5, seed=10_000 + seed)
                report = evaluate_conditional(
                    (sim.first, sim.second), None, sim.replicates, sim.K1, sim.K2, sim.motion, draws=draws, calibration_refits=refits, seed=seed
                )
                start, stop = report["diagnostics"]["window_frames"]
                truth = sim.true_difference(slice(start, stop))
                for name, result in report["angles"].items():
                    if injected and name != "right_elbow_flexion":
                        continue
                    stream.write(json.dumps({
                        "noise_px": noise_px, "scenario": label, "seed": seed, "angle": name,
                        "margin": result["margin_deg"],
                        "true_mean": float(truth[name].mean()),
                        "true_rms": float(np.sqrt(np.mean(truth[name] ** 2))),
                        "true_max": float(np.abs(truth[name]).max()),
                        "mean_ci": result["mean_ci_deg"], "rms_ci": result["rms_ci_deg"],
                        "decisions": {
                            "mean": result["mean_decision"], "rms": result["rms_decision"],
                            "whole_curve": result["curve_decision"],
                        },
                        "replicate_scalar_pass": result["replicate_check"]["pass"],
                    }) + "\n")
                stream.flush()


def summary(path: Path) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["noise_px"], row["scenario"])].append(row)
    print(f"{'noise':>5} {'scenario':34} {'n':>3}  P(EQUIVALENT) mean / rms / curve     truth-in-CI mean / rms")
    for (noise, label), items in sorted(groups.items()):
        rate = lambda claim: np.mean([r["decisions"][claim] == EQUIVALENT for r in items])
        cover_mean = np.mean([r["mean_ci"][0] <= r["true_mean"] <= r["mean_ci"][1] for r in items])
        cover_rms = np.mean([r["true_rms"] <= r["rms_ci"][1] for r in items])
        print(f"{noise:5.1f} {label:34} {len(items):3d}  {rate('mean'):.3f} / {rate('rms'):.3f} / {rate('whole_curve'):.3f}"
              f"           {cover_mean:.3f} / {cover_rms:.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--noise-px", type=float, default=2.0)
    parser.add_argument("--seeds", type=int, default=60)
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--refits", type=int, default=40)
    parser.add_argument("--only", help="run a single scenario")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.summary:
        summary(args.output)
    else:
        run(args.noise_px, args.seeds, args.output, args.draws, args.refits, args.only)
