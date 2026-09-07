#!/usr/bin/env python3
"""Resumably compile persistent single-sign and directed-pair live motion artifacts."""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import SessionLocal, init_db  # noqa: E402
from app.services.compose_service import ComposeError  # noqa: E402
from app.services.live_motion_service import (  # noqa: E402
    cached_composition,
    canonical_clips,
    library_version,
    readiness,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after this many uncached artifacts (0 compiles all).")
    parser.add_argument("--gloss", action="append", default=[],
                        help="Compile only pairs touching this gloss; may be repeated.")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry artifacts previously persisted as rejected.")
    args = parser.parse_args()
    init_db()
    built = failed = 0
    selected = {value.upper() for value in args.gloss}
    with SessionLocal() as session:
        clips = canonical_clips(session)
        version = library_version(session)
        jobs = [(clip,) for clip in clips]
        jobs.extend(itertools.product(clips, repeat=2))
        for job in jobs:
            if selected and not any(clip.gloss.name in selected for clip in job):
                continue
            try:
                _payload, hit = cached_composition(
                    session, list(job), version, retry_failed=args.retry_failed, allow_compile=True,
                )
                state = "cached" if hit else "built"
                print(f"{state:6} {' -> '.join(clip.gloss.name for clip in job)}")
                if not hit:
                    built += 1
            except ComposeError as exc:
                failed += 1
                print(f"failed {' -> '.join(clip.gloss.name for clip in job)}: {exc}")
            if args.limit and built >= args.limit:
                break
        state = readiness(session)
        print(
            f"library={version} built={built} failed={failed} "
            f"transitions={state['compiledTransitions']}/{state['requiredTransitions']}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
