"""Audit all ordered canonical pairs (including repeats), without claiming ISL correctness."""
from __future__ import annotations

import argparse
from datetime import datetime, UTC
import itertools
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.core.db import SessionLocal
from app.ingest.compose import ALGORITHM_VERSION
from app.models import SignClip, Gloss
from app.services.compose_service import ComposeError, compose_clips


def audit(clips):
    results = []
    for first, second in itertools.product(clips, repeat=2):
        try:
            composed, warnings = compose_clips([(first.gloss.name, first), (second.gloss.name, second)])
            row = {"status": "direct", "frameCount": composed.track.frame_count,
                   "quality": composed.blend_quality, "warnings": warnings}
        except ComposeError as exc:
            row = {"status": "rejected", "error": str(exc), "quality": exc.blend_quality}
        results.append({"signs": [first.gloss.name, second.gloss.name],
                        "contentHashes": [first.content_hash, second.content_hash], **row})
    return {"algorithmVersion": ALGORITHM_VERSION, "generatedAt": datetime.now(UTC).isoformat(),
            "purpose": "Motion audit only; not ISL sentence approval.",
            "clipCount": len(clips), "pairCount": len(results),
            "passing": sum(r["status"] == "direct" for r in results),
            "rejected": sum(r["status"] == "rejected" for r in results), "pairs": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with SessionLocal() as session:
        clips = session.scalars(select(SignClip).join(Gloss).where(SignClip.is_canonical.is_(True)).order_by(Gloss.name)).all()
        result = audit(clips)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k != "pairs"}))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
