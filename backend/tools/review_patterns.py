"""Prepare a review worksheet, or validate the checked-in registry. Never auto-approves ISL."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.core.db import SessionLocal
from app.models import SignClip
from app.services.translate_service import load_registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worksheet", action="store_true")
    args = parser.parse_args()
    registry = load_registry()
    if not args.worksheet:
        print(f"Valid ISL registry v{registry.version}: {len(registry.patterns)} patterns; "
              f"{sum(p.reviewStatus == 'approved' for p in registry.patterns)} approved.")
        return
    with SessionLocal() as session:
        clips = session.scalars(select(SignClip).where(SignClip.is_canonical.is_(True))).all()
        records = {clip.gloss.name: {
            "contentHash": clip.content_hash, "clipId": clip.id, "phases": clip.qc.get("phases"),
            "checks": {"vocabularyIdentity": False, "semanticBoundaries": False,
                       "avatarIntelligibility": False},
        } for clip in clips}
    print(json.dumps({"registry": registry.model_dump(), "recordings": records,
                      "instructions": "A fluent ISL reviewer must check meaning and rendered signing with Deaf ISL users. Enter reviewer, date, evidence, and reviewedClipHashes before approving a pattern; increment registry version."}, indent=2))


if __name__ == "__main__":
    main()
