import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.ingest import clipfmt


def _clip(frames=120, bones=46, root=True):
    rng = np.random.default_rng(7)
    rots = {
        f"Bone{i}": Rotation.from_quat(
            rng.normal(size=(frames, 4)) / np.linalg.norm(rng.normal(size=(frames, 4)), axis=1, keepdims=True)
            if False else Rotation.random(frames, random_state=i).as_quat()
        )
        for i in range(bones)
    }
    positions = rng.normal(size=(frames, 3)) if root else None
    return clipfmt.from_rotations(rots, fps=60.0, rig_digest="a1b2c3d4e5f60718", root_positions=positions)


def test_round_trip_preserves_rotations_within_quantisation():
    clip = _clip()
    out = clipfmt.decode(clipfmt.encode(clip))

    assert out.bone_names == clip.bone_names
    assert out.fps == clip.fps
    assert out.frame_count == clip.frame_count
    assert out.rig_digest == clip.rig_digest

    a = Rotation.from_quat(clip.rotations.reshape(-1, 4))
    b = Rotation.from_quat(out.rotations.reshape(-1, 4))
    err = np.degrees((a.inv() * b).magnitude())
    assert err.max() < 0.02, f"worst quantisation error {err.max():.4f} deg"


def test_round_trip_preserves_root_motion():
    clip = _clip()
    out = clipfmt.decode(clipfmt.encode(clip))
    assert np.allclose(out.root_positions, clip.root_positions, atol=1e-6)


def test_clip_without_root_motion():
    clip = _clip(root=False)
    out = clipfmt.decode(clipfmt.encode(clip))
    assert out.root_positions is None


def test_size_stays_within_budget():
    """A two-second sign must stay small enough to stream instantly."""
    blob = clipfmt.encode(_clip(frames=120, bones=46))
    assert len(blob) < 80_000, f"{len(blob)} bytes is larger than expected"


def test_rejects_a_foreign_blob():
    with pytest.raises(clipfmt.ClipFormatError, match="magic"):
        clipfmt.decode(b"NOTACLIP" + b"\x00" * 64)


def test_rejects_a_truncated_blob():
    with pytest.raises(clipfmt.ClipFormatError):
        clipfmt.decode(b"SG")
