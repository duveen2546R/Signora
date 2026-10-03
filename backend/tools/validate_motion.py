"""Run the prespecified primary mixed-effects analysis on paired motion scores."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Allow `python backend/tools/validate_motion.py` as well as module execution.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.validation.mixed_effects import ValidationError, analyse_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scores", type=Path, help="CSV with one row per matched performance")
    parser.add_argument("--output", type=Path, required=True, help="Directory for auditable results")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--meaningful-reduction", type=float, default=0.20)
    args = parser.parse_args(argv)

    try:
        frame, report = analyse_csv(
            args.scores, alpha=args.alpha, meaningful_reduction=args.meaningful_reduction,
        )
    except ValidationError as exc:
        parser.exit(2, f"Validation error: {exc}\n")

    args.output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output / "paired_performance_scores.csv", index=False)
    (args.output / "primary_lmem.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
