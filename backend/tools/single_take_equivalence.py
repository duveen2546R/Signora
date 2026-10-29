"""Single-take equivalence: front video + oblique (30-45 deg) video + FBX of the same performance.

Example:
    python tools/single_take_equivalence.py --front front.mp4 --oblique side.mp4 \\
        --fbx sign.fbx --output results/sign
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.validation.mixed_effects import ValidationError  # noqa: E402
from app.validation.single_take_job import DEFAULT_FOCAL_35MM, run_single_take  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--front", required=True, type=Path, help="frontal sign video")
    parser.add_argument("--oblique", required=True, type=Path, help="30-45 deg sign video")
    parser.add_argument("--fbx", required=True, type=Path, help="suit FBX of the same performance")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--noise-front", type=Path, help="optional noise recording, front phone")
    parser.add_argument("--noise-oblique", type=Path, help="optional noise recording, oblique phone")
    parser.add_argument("--still", nargs=2, type=float, default=(0.5, 9.5), metavar=("START", "END"),
                        help="seconds of stillness in the noise recording (default 0.5 9.5)")
    parser.add_argument("--focal-35mm", nargs="+", type=float, metavar="MM",
                        help=f"35 mm-equivalent focal length, one value or front/oblique (default {DEFAULT_FOCAL_35MM})")
    parser.add_argument("--fixed-focal", action="store_true", help="trust the focal length exactly")
    parser.add_argument("--replicates", type=int, default=5, help="test-time augmentations (5 max)")
    parser.add_argument("--draws", type=int, default=1000, help="Monte Carlo draws")
    args = parser.parse_args(argv)
    focal = None
    if args.focal_35mm:
        focal = tuple(args.focal_35mm) if len(args.focal_35mm) == 2 else args.focal_35mm[0]
    try:
        report = run_single_take(
            args.front, args.oblique, args.fbx, args.output,
            noise_front=args.noise_front, noise_oblique=args.noise_oblique, still_s=tuple(args.still),
            focal_35mm=focal, refine_focal=not args.fixed_focal,
            replicates=args.replicates, draws=args.draws,
        )
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"\nOverall: {report['decision']} ({report['primary_claim']} claim)")
    for name, result in report["angles"].items():
        print(
            f"  {name}: {result['decision']}  mean {result['mean_difference_deg']:+.2f} deg "
            f"(90% CI {result['mean_ci_deg'][0]:+.2f} to {result['mean_ci_deg'][1]:+.2f}), "
            f"band max |{result['max_band_abs_deg']:.1f}| deg vs margin {result['margin_deg']:.1f}, "
            f"spm1d replicates {'pass' if result['replicate_spm1d']['pass'] else 'fail'}"
        )
    d = report["diagnostics"]
    print(f"  calibration: baseline {d['baseline_angle_deg']:.1f} deg, reprojection {d['reprojection_rms_px']:.2f} px, "
          f"focal {d['focal_px'][0]:.0f}/{d['focal_px'][1]:.0f} px")
    print(f"  noise ({report['noise_model']['source']}): "
          f"{[round(sum(v) / len(v), 2) for v in report['noise_model']['used_sigma_px']]} px per view")
    print(f"  {report['scope']}")
    print(f"  report: {args.output / 'single_take_report.json'}\n  figure: {args.output / report['figure']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
