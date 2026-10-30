"""Run the combined single-take protocol on real files: two sign videos + one FBX.

Shared by `tools/single_take_equivalence.py` and the analysis worker, so both produce the same
report.json and figure.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .conditional_equivalence import evaluate_conditional, primary_claim
from .equivalence_single_take import EQUIVALENT, INCONCLUSIVE, NOT_EQUIVALENT, load_margins
from .fbx_motion import load_motion
from .mixed_effects import ValidationError
from .multiview import focal_from_35mm, intrinsics
from .trials import sha256
from .video_replicates import extract_replicated_views

# Phone main cameras are ~26 mm-equivalent for photos; the 16:9 video crop and stabilisation
# make the video frame ~28 mm-equivalent. Used only when the user does not supply a value.
DEFAULT_FOCAL_35MM = 28.0
REPORT = "single_take_report.json"
FIGURE = "single_take_equivalence.png"


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    return value


def run_single_take(
    front_video: str | Path,
    oblique_video: str | Path,
    fbx: str | Path,
    output: str | Path,
    *,
    noise_front: str | Path | None = None,
    noise_oblique: str | Path | None = None,
    still_s: tuple[float, float] = (0.5, 9.5),
    focal_35mm: tuple[float, float] | float | None = None,
    refine_focal: bool = True,
    replicates: int = 5,
    draws: int = 1000,
    progress=print,
) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "pose-cache"
    if (noise_front is None) != (noise_oblique is None):
        raise ValidationError("A noise recording needs both the front and the oblique video.")

    def extract(path, label):
        progress(f"Extracting keypoints ({label}) with {replicates} test-time augmentations...")
        return extract_replicated_views(
            path, replicates=replicates, cache_dir=cache,
            progress=lambda i, n: progress(f"  {label}: frame {i}/{n}") if i % 30 == 0 else None,
        )

    front, front_reps, front_meta = extract(front_video, "front")
    oblique, oblique_reps, oblique_meta = extract(oblique_video, "oblique")
    noise = None
    if noise_front is not None:
        noise_a, _, _ = extract(noise_front, "noise front")
        noise_b, _, _ = extract(noise_oblique, "noise oblique")
        noise = (noise_a, noise_b)

    focal = focal_35mm if isinstance(focal_35mm, (tuple, list)) else (focal_35mm, focal_35mm)
    focal = tuple(DEFAULT_FOCAL_35MM if value is None else float(value) for value in focal)
    K1 = intrinsics(*front.size, focal_from_35mm(focal[0], *front.size))
    K2 = intrinsics(*oblique.size, focal_from_35mm(focal[1], *oblique.size))
    motion = load_motion(fbx, include_elbows=True)

    progress(f"Calibrating, propagating measurement error ({draws} draws) and testing...")
    report = evaluate_conditional(
        (front, oblique), noise, tuple(zip(front_reps, oblique_reps)), K1, K2, motion,
        still_s=still_s, refine_focal=refine_focal, draws=draws,
    )
    report["inputs"] = {
        "front_video": front_meta, "oblique_video": oblique_meta,
        "fbx": {"file": Path(fbx).name, "sha256": sha256(fbx), "profile": motion.profile, "fps": motion.fps},
        "noise_recording": noise is not None,
        "focal_35mm_assumed": list(focal),
        "focal_refined": refine_focal,
        "margins_deg": load_margins(),
        "primary_claim": primary_claim(),
    }
    report["figure"] = FIGURE
    report = _json_safe(report)
    (output / REPORT).write_text(json.dumps(report, indent=2) + "\n")
    plot_report(report, output / FIGURE)
    return report


def plot_report(report: dict, path: Path) -> None:
    """One row per angle: curves on the left, offset-corrected difference and band on the right."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    angles = report["angles"]
    figure, axes = plt.subplots(len(angles), 2, figsize=(12, 2.6 * len(angles) + 1.2), squeeze=False)
    colours = {EQUIVALENT: "#1b7f3b", NOT_EQUIVALENT: "#b3261e", INCONCLUSIVE: "#8a6d00"}
    for row, (name, result) in enumerate(angles.items()):
        phase = np.array(result["curve_phase"]) * 100
        left, right = axes[row]
        fbx = np.array(result["fbx_curve_deg"])
        left.plot(phase, fbx, color="#333", label="FBX")
        left.plot(phase, result.get("video_curve_deg", fbx + np.array(result["observed_deg"])), color="#1565c0", label="Video")
        if result.get("static_offset_deg"):
            left.plot(phase, fbx + np.array(result["observed_deg"]), color="#1565c0", linestyle="--",
                      label=f"Video - offset ({result['static_offset_deg']:+.1f} deg)")
        left.set_ylabel(name.replace("_", " ") + " (deg)", fontsize=8)
        left.legend(frameon=False, fontsize=7)
        margin = result["margin_deg"]
        right.fill_between(phase, result["band_lower_deg"], result["band_upper_deg"], color="#90caf9", alpha=0.6)
        right.plot(phase, result["curve_deg"], color="#1565c0")
        for bound in (-margin, margin):
            right.axhline(bound, color="#b3261e", linestyle="--", linewidth=1)
        right.axhline(0, color="#999", linewidth=0.8)
        rms_low, rms_high = result["rms_ci_deg"]
        right.set_title(
            f"{result['decision']}  RMS {result['rms_deg']:.1f} deg (upper {rms_high:.1f}), raw {result.get('raw_rms_deg', result['rms_deg']):.1f}",
            color=colours[result["decision"]], fontsize=8, fontweight="bold",
        )
    for column in range(2):
        axes[-1, column].set_xlabel("Sign phase (%)")
    figure.suptitle(
        f"Overall: {report['decision']}  ({report['primary_claim'].replace('_', ' ')} claim, "
        f"offset rule: {report['diagnostics'].get('offset_rule') or 'none'})", fontweight="bold",
    )
    figure.text(0.5, 0.005, report["scope"], ha="center", fontsize=7, wrap=True)
    figure.tight_layout(rect=(0, 0.02, 1, 0.98))
    figure.savefig(path, dpi=110)
    plt.close(figure)
