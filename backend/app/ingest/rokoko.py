"""Parse a Rokoko Studio biomechanics CSV into typed arrays.

Fails loudly on any header it does not recognise. A silently mis-mapped column would produce
plausible-looking motion that is subtly wrong, which is far more expensive than a hard error.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import skeleton as sk


class RokokoFormatError(ValueError):
    """The CSV is not the biomechanics export this pipeline understands."""


# Reviewed captures need enough measured preparation and retraction to provide a natural neutral
# fallback, plus a sign range long enough not to be a boundary-click mistake.
MIN_REVIEWED_EDGE_SECONDS = 0.12
MIN_REVIEWED_SIGN_SECONDS = 0.30


# Columns the pipeline understands but Rokoko does not produce. Anything outside this set is still
# rejected: the strictness exists so a differently-configured export fails loudly instead of being
# silently mis-mapped, and that guarantee should not be traded away for one hand-added column.
OPTIONAL_COLUMNS = frozenset({"Phase"})

PHASE_COLUMN = "Phase"
PHASE_START = "start"
PHASE_SIGN = "sign"
PHASE_END = "end"
PHASE_ORDER = (PHASE_START, PHASE_SIGN, PHASE_END)


@dataclass(frozen=True)
class Take:
    """One parsed recording."""

    name: str
    times: np.ndarray                 # (F,) seconds, starting at 0
    positions: np.ndarray             # (F, len(SEGMENTS), 3) metres, Y-up, left-handed
    angles: dict[str, np.ndarray]     # channel name -> (F,) degrees
    segment_index: dict[str, int]

    # Hand-authored phase boundaries, in seconds from the start of the take, when the CSV carries a
    # `Phase` column. Stored as times rather than frame indices because the ingest pipeline trims
    # corrupt frames and resamples 30 -> 60 fps; indices do not survive that, seconds do.
    sign_start_s: float | None = None
    sign_end_s: float | None = None
    phase_source: str | None = None
    phase_reviewed: bool = False

    @property
    def has_phase_bounds(self) -> bool:
        return self.sign_start_s is not None and self.sign_end_s is not None

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
    missing = expected - found
    unknown = found - expected - OPTIONAL_COLUMNS
    if missing or unknown:
        raise RokokoFormatError(
            f"{path.name}: column set does not match the known biomechanics schema "
            f"({len(found)} columns, expected {len(expected)}). "
            f"Missing e.g. {sorted(missing)[:5]}; unexpected e.g. {sorted(unknown)[:5]}. "
            f"Recognised optional columns: {sorted(OPTIONAL_COLUMNS)}. "
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

    sign_start_s, sign_end_s = _read_phase_column(df, times, path.name)

    return Take(
        name=name or path.stem,
        times=times,
        positions=positions,
        angles=angles,
        segment_index=segment_index,
        sign_start_s=sign_start_s,
        sign_end_s=sign_end_s,
        phase_source="authored-csv" if sign_start_s is not None else None,
        phase_reviewed=sign_start_s is not None,
    )


def with_phase_bounds(
    take: Take,
    sign_start_s: float | None,
    sign_end_s: float | None,
    *,
    source: str = "authored-ui",
) -> Take:
    """Validate user-authored sign boundaries and attach them to a parsed take."""
    if (sign_start_s is None) != (sign_end_s is None):
        raise RokokoFormatError("sign start and sign end timestamps must be supplied together")
    if sign_start_s is None:
        return take

    start, end = float(sign_start_s), float(sign_end_s)
    if not np.isfinite(start) or not np.isfinite(end):
        raise RokokoFormatError("sign timestamps must be finite numbers")
    step = float(np.median(np.diff(take.times))) if take.frame_count > 1 else 0.0
    clip_end = float(take.times[-1] + step) if take.frame_count else 0.0
    if start < 0 or end <= start or end > clip_end + 1e-9:
        raise RokokoFormatError(
            f"sign timestamps must satisfy 0 <= start < end <= {clip_end:.3f}s"
        )
    if (
        start < MIN_REVIEWED_EDGE_SECONDS
        or clip_end - end < MIN_REVIEWED_EDGE_SECONDS
        or end - start < MIN_REVIEWED_SIGN_SECONDS
    ):
        raise RokokoFormatError(
            "capture must include at least 0.120s of Start, 0.300s of Sign, "
            "and 0.120s of End motion"
        )

    if take.has_phase_bounds:
        tolerance = max(step / 2.0, 1e-6)
        if abs(start - take.sign_start_s) > tolerance or abs(end - take.sign_end_s) > tolerance:
            raise RokokoFormatError(
                "capture-form timestamps conflict with the CSV Phase column; "
                "remove one source or make the boundaries agree"
            )

    return replace(
        take,
        sign_start_s=start,
        sign_end_s=end,
        phase_source=source,
        phase_reviewed=True,
    )


def _read_phase_column(
    df: pd.DataFrame, times: np.ndarray, filename: str
) -> tuple[float | None, float | None]:
    """Read hand-authored `start` / `sign` / `end` labels into the two boundary times.

    The labels must form contiguous runs in that order. A missing `start` or `end` run is allowed -
    plenty of recordings were cut before the hand returned to rest - but an empty or absent `sign`
    run is not, because there would be nothing left to play.
    """
    if PHASE_COLUMN not in df.columns:
        return None, None

    raw = df[PHASE_COLUMN].fillna("").astype(str).str.strip().str.lower().to_numpy()
    labelled = np.where(raw != "")[0]
    if labelled.size == 0:
        return None, None

    if labelled.size != len(raw):
        blank = int(np.where(raw == "")[0][0]) + 2
        raise RokokoFormatError(
            f"{filename}: row {blank} has a blank {PHASE_COLUMN} value. "
            "When the column is used, every frame must be labelled start, sign, or end."
        )

    unknown = sorted(set(raw[labelled]) - set(PHASE_ORDER))
    if unknown:
        row = int(labelled[np.argmax(np.isin(raw[labelled], unknown))]) + 2  # +2: header, 1-based
        raise RokokoFormatError(
            f"{filename}: row {row} has an unrecognised {PHASE_COLUMN} value {unknown[0]!r}. "
            f"Expected one of {list(PHASE_ORDER)}, or blank."
        )

    # Each label must appear as a single contiguous run, and the runs must be in order.
    seen: list[str] = []
    for index in labelled:
        label = raw[index]
        if not seen or seen[-1] != label:
            if label in seen:
                raise RokokoFormatError(
                    f"{filename}: row {int(index) + 2} returns to {PHASE_COLUMN} {label!r} after "
                    "leaving it; each phase must be one contiguous block."
                )
            seen.append(label)

    order = [PHASE_ORDER.index(label) for label in seen]
    if order != sorted(order):
        raise RokokoFormatError(
            f"{filename}: {PHASE_COLUMN} runs are out of order ({' -> '.join(seen)}). "
            f"Expected {' -> '.join(PHASE_ORDER)}."
        )

    sign = np.where(raw == PHASE_SIGN)[0]
    if sign.size == 0:
        raise RokokoFormatError(
            f"{filename}: {PHASE_COLUMN} is annotated but has no {PHASE_SIGN!r} rows; "
            "there would be nothing left to play."
        )

    start_index = int(sign[0])
    end_index = int(sign[-1]) + 1
    # End is exclusive. When the sign reaches the final sample there is no timestamp for the
    # following frame, so extrapolate one source-frame interval instead of dropping the last frame.
    if end_index < len(times):
        end_time = float(times[end_index])
    else:
        step = float(np.median(np.diff(times))) if len(times) > 1 else 0.0
        end_time = float(times[-1] + step)
    return float(times[start_index]), end_time


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
