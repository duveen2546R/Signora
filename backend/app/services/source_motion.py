"""Verify stored normalized motion against its immutable source capture."""
import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from app.ingest.landmarks import LandmarkTake, to_landmarks
from app.ingest.fbx import parse_fbx
from app.ingest.rokoko import parse_csv, with_phase_bounds


def load_source_motion(path: Path, source_capture: str, *, validate_stored_phases: bool = True):
    raw = LandmarkTake.from_payload(json.loads(path.read_text()))
    if Path(source_capture).suffix.lower() == ".fbx":
        source = parse_fbx(source_capture)
        captured = source
    else:  # Read-only compatibility for pre-FBX assets while they are being replaced.
        source = parse_csv(source_capture)
        captured = to_landmarks(source)
    if captured.frame_count != raw.frame_count or any(
        not np.allclose(getattr(captured, key), getattr(raw, key), atol=0.00006, rtol=0)
        for key in ("pose", "left_hand", "right_hand", "face_blendshapes")
    ):
        raise ValueError("Stored motion does not match its source capture; re-ingest it.")
    if raw.timestamps is not None and not np.allclose(raw.times, source.times, atol=1e-9, rtol=0):
        raise ValueError("Stored timestamps do not match the source capture; re-ingest it.")
    if validate_stored_phases and raw.phase_reviewed:
        checked = with_phase_bounds(
            source, raw.sign_start_s, raw.sign_end_s, snap=True, override_csv_phase=True,
        )
        raw = replace(raw, sign_start_s=checked.sign_start_s, sign_end_s=checked.sign_end_s)
    return replace(raw, timestamps=source.times.copy()), source


def raw_payload(raw, source):
    payload = raw.to_payload()
    payload["csvPhaseBounds"] = ({"signStartSeconds": source.sign_start_s,
                                  "signEndSeconds": source.sign_end_s}
                                 if source.has_phase_bounds else None)
    return payload
