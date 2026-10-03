"""Independent FBX/video validation: extract, verify, score, and secondary analyses."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.validation.mixed_effects import ValidationError  # noqa: E402
from app.validation.power import simulate_power  # noqa: E402
from app.validation.scoring import run_manifest  # noqa: E402
from app.validation.secondary import (  # noqa: E402
    constrained_dtw_sensitivity, functional_limits_of_agreement, spm1d_paired_curves,
)
from app.validation.trials import load_manifest, sha256  # noqa: E402
from app.validation.video_pose import extract_video_pose  # noqa: E402


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    digest = sub.add_parser("hash", help="SHA-256 hashes for source files")
    digest.add_argument("files", nargs="+", type=Path)
    verify = sub.add_parser("verify", help="Check matches, files, hashes, and study windows")
    verify.add_argument("manifest", type=Path)
    extract = sub.add_parser("extract-video", help="Write editable MediaPipe pose landmarks")
    extract.add_argument("video", type=Path)
    extract.add_argument("--pose-model", required=True, type=Path)
    extract.add_argument("--output", required=True, type=Path)
    score = sub.add_parser("score", help="Score every matched trial or fail the whole batch")
    score.add_argument("manifest", type=Path)
    score.add_argument("--output", required=True, type=Path)
    floa = sub.add_parser("floa", help="Action-specific descriptive functional LoA")
    floa.add_argument("scores_dir", type=Path)
    floa.add_argument("--output", required=True, type=Path)
    floa.add_argument("--bootstraps", type=int, default=1000)
    spm = sub.add_parser("spm1d", help="Action-specific paired waveform inference")
    spm.add_argument("scores_dir", type=Path)
    spm.add_argument("--output", required=True, type=Path)
    dtw = sub.add_parser("dtw", help="Constrained two-wrist spatial sensitivity")
    dtw.add_argument("scores_dir", type=Path)
    dtw.add_argument("--output", required=True, type=Path)
    power = sub.add_parser("power", help="Pilot-informed held-out sample-size simulation")
    power.add_argument("pilot_scores", type=Path)
    power.add_argument("--output", required=True, type=Path)
    power.add_argument("--actions", type=int, nargs="+", default=[8, 16, 32, 48])
    power.add_argument("--performers", type=int, default=3)
    power.add_argument("--repetitions", type=int, default=3)
    power.add_argument("--assumed-true-reduction", type=float, default=0.30)
    power.add_argument("--meaningful-threshold", type=float, default=0.20)
    power.add_argument("--simulations", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        if args.command == "hash":
            result = {str(path): sha256(path) for path in args.files}
        elif args.command == "verify":
            trials = load_manifest(args.manifest)
            result = {"verified_trials": len(trials), "performance_ids": [t.performance_id for t in trials]}
        elif args.command == "extract-video":
            result = extract_video_pose(args.video, args.pose_model, args.output)
        elif args.command == "score":
            result = run_manifest(args.manifest, args.output)
        elif args.command == "floa":
            result = functional_limits_of_agreement(args.scores_dir, bootstraps=args.bootstraps)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(_json_safe(result), indent=2, allow_nan=False) + "\n")
        elif args.command == "spm1d":
            result = spm1d_paired_curves(args.scores_dir)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(_json_safe(result), indent=2, allow_nan=False) + "\n")
        elif args.command == "dtw":
            result = constrained_dtw_sensitivity(args.scores_dir)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(_json_safe(result), indent=2, allow_nan=False) + "\n")
        else:
            result = simulate_power(
                str(args.pilot_scores), action_counts=tuple(args.actions),
                performers=args.performers, repetitions=args.repetitions,
                assumed_true_reduction=args.assumed_true_reduction,
                meaningful_threshold=args.meaningful_threshold,
                simulations=args.simulations,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(_json_safe(result), indent=2, allow_nan=False) + "\n")
    except (ValidationError, OSError) as exc:
        parser.exit(2, f"Validation error: {exc}\n")
    print(json.dumps(_json_safe(result), indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
