"""The `.signclip` binary format: retargeted local rotations ready for Unity to play back.

Little-endian throughout. Rotations are quantised to int16 per component, which is ~0.006 degrees of
resolution - far below what is visible - and keeps a two-second sign at 60 fps around 58 KB.

    magic          char[4]   "SGNC"
    version        u16
    flags          u16       bit0 = has root motion
    fps            f32
    frameCount     u32
    boneCount      u16
    rigDigest      u64       rejects a clip retargeted for a different avatar
    boneTable      boneCount x (u8 nameLength + utf8 name)
    rootPositions  f32[3] x frameCount     (present only if bit0)
    rotations      i16[4] x boneCount x frameCount   (x, y, z, w scaled by 32767)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation

MAGIC = b"SGNC"
VERSION = 1
FLAG_ROOT_MOTION = 1 << 0
_HEADER = "<4sHHfIHQ"
_SCALE = 32767.0


class ClipFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Clip:
    fps: float
    bone_names: list[str]
    rotations: np.ndarray            # (F, B, 4) quaternions [x, y, z, w]
    root_positions: np.ndarray | None  # (F, 3) or None
    rig_digest: str

    @property
    def frame_count(self) -> int:
        return self.rotations.shape[0]

    @property
    def duration(self) -> float:
        return self.frame_count / self.fps if self.fps else 0.0


def from_rotations(
    locals_: dict[str, Rotation],
    fps: float,
    rig_digest: str,
    root_positions: np.ndarray | None = None,
) -> Clip:
    names = list(locals_.keys())
    quats = np.stack([locals_[n].as_quat() for n in names], axis=1)  # (F, B, 4)
    return Clip(
        fps=fps, bone_names=names, rotations=quats,
        root_positions=root_positions, rig_digest=rig_digest,
    )


def encode(clip: Clip) -> bytes:
    flags = FLAG_ROOT_MOTION if clip.root_positions is not None else 0
    digest = int(clip.rig_digest[:16], 16)

    parts = [struct.pack(
        _HEADER, MAGIC, VERSION, flags, float(clip.fps),
        clip.frame_count, len(clip.bone_names), digest,
    )]

    for name in clip.bone_names:
        raw = name.encode("utf-8")
        if len(raw) > 255:
            raise ClipFormatError(f"bone name too long: {name}")
        parts.append(struct.pack("<B", len(raw)) + raw)

    if clip.root_positions is not None:
        parts.append(np.ascontiguousarray(clip.root_positions, dtype="<f4").tobytes())

    # Canonicalise sign (q and -q are the same rotation) so quantisation never flips a frame.
    q = np.asarray(clip.rotations, dtype=np.float64)
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    q = np.where(q[..., 3:4] < 0, -q, q)
    quant = np.rint(np.clip(q, -1.0, 1.0) * _SCALE).astype("<i2")
    parts.append(np.ascontiguousarray(quant).tobytes())

    return b"".join(parts)


def decode(blob: bytes) -> Clip:
    size = struct.calcsize(_HEADER)
    if len(blob) < size:
        raise ClipFormatError("blob is shorter than the header.")
    magic, version, flags, fps, frames, bones, digest = struct.unpack(_HEADER, blob[:size])
    if magic != MAGIC:
        raise ClipFormatError(f"bad magic {magic!r}, expected {MAGIC!r}.")
    if version != VERSION:
        raise ClipFormatError(f"unsupported .signclip version {version}.")

    off = size
    names: list[str] = []
    for _ in range(bones):
        n = blob[off]
        off += 1
        names.append(blob[off:off + n].decode("utf-8"))
        off += n

    root = None
    if flags & FLAG_ROOT_MOTION:
        count = frames * 3
        root = np.frombuffer(blob, dtype="<f4", count=count, offset=off).reshape(frames, 3)
        off += count * 4

    count = frames * bones * 4
    quant = np.frombuffer(blob, dtype="<i2", count=count, offset=off).reshape(frames, bones, 4)
    quats = quant.astype(np.float64) / _SCALE
    quats /= np.linalg.norm(quats, axis=-1, keepdims=True)

    return Clip(
        fps=float(fps), bone_names=names, rotations=quats,
        root_positions=None if root is None else np.asarray(root, dtype=np.float64),
        rig_digest=f"{digest:016x}",
    )
