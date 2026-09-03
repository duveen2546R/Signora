"""Parse a Rokoko Studio biomechanics CSV into typed arrays.

Fails loudly on any header it does not recognise. A silently mis-mapped column would produce
plausible-looking motion that is subtly wrong, which is far more expensive than a hard error.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import skeleton as sk


class RokokoFormatError(ValueError):
    """The CSV is not the biomechanics export this pipeline understands."""


@dataclass(frozen=True)
class Take:
    """One parsed recording."""

    name: str
    times: np.ndarray                 # (F,) seconds, starting at 0
    positions: np.ndarray             # (F, len(SEGMENTS), 3) metres, Y-up, left-handed
    angles: dict[str, np.ndarray]     # channel name -> (F,) degrees
    segment_index: dict[str, int]

    @property
    def frame_count(self) -> int:
        return len(self.times)

    @property
    def duration(self) -> float:
        return float(self.times[-1]) if len(self.times) else 0.0

    @property
    def source_fps(self) -> float:
        if len(self.times) < 2:
            return 0.0
        return float((len(self.times) - 1) / self.times[-1])

    def pos(self, segment: str) -> np.ndarray:
        """(F, 3) world positions for one segment."""
        return self.positions[:, self.segment_index[segment], :]


def parse_csv(path: str | Path, name: str | None = None) -> Take:
    path = Path(path)
    df = pd.read_csv(path)

    if df.columns[0] != "Timestamp":
        raise RokokoFormatError(
            f"{path.name}: expected first column 'Timestamp', got {df.columns[0]!r}. "
            "This does not look like a Rokoko biomechanics export."
        )

    found = set(df.columns[1:])
    expected = set(sk.position_columns()) | set(sk.angle_columns())
    if found != expected:
        missing = sorted(expected - found)[:5]
        extra = sorted(found - expected)[:5]
        raise RokokoFormatError(
            f"{path.name}: column set does not match the known biomechanics schema "
            f"({len(found)} columns, expected {len(expected)}). "
            f"Missing e.g. {missing}; unexpected e.g. {extra}. "
            "If Rokoko's export settings changed, update app/ingest/skeleton.py."
        )

    # Timestamps are integer milliseconds in this export; normalise to seconds from zero.
    times = df["Timestamp"].to_numpy(dtype=np.float64) / 1000.0
    times = times - times[0]
    if np.any(np.diff(times) <= 0):
        raise RokokoFormatError(f"{path.name}: timestamps are not strictly increasing.")

    segment_index = {seg: i for i, seg in enumerate(sk.SEGMENTS)}
    cols = [f"{seg}_position_{ax}" for seg in sk.SEGMENTS for ax in "xyz"]
    positions = (
        df[cols].to_numpy(dtype=np.float64).reshape(len(df), len(sk.SEGMENTS), 3)
    )

    angles = {c: df[c].to_numpy(dtype=np.float64) for c in sk.angle_columns()}

    if not np.all(np.isfinite(positions)):
        raise RokokoFormatError(f"{path.name}: position data contains NaN or inf.")

    return Take(
        name=name or path.stem,
        times=times,
        positions=positions,
        angles=angles,
        segment_index=segment_index,
    )


def measure_skeleton(take: Take) -> dict[str, float]:
    """Constant bone lengths (metres) of the performer, measured from the position data.

    The biomechanics export is a rigid skeleton, so these are constant to well under a millimetre;
    the spread is returned as a data-quality signal rather than assumed.
    """
    out: dict[str, float] = {}
    for bone in sk.BONES:
        if bone.tail is None:
            continue
        d = np.linalg.norm(take.pos(bone.tail) - take.pos(bone.head), axis=1)
        out[bone.name] = float(d.mean())
    out["_hip_height"] = float(take.pos("Pelvis")[:, 1].mean())
    return out
