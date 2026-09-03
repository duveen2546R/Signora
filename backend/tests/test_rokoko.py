"""The parser must agree with the real export, and reject anything else."""
import numpy as np
import pytest

from app.ingest import skeleton as sk
from app.ingest.rokoko import RokokoFormatError, measure_skeleton, parse_csv


def test_schema_matches_the_real_export(hello_take):
    assert hello_take.positions.shape == (hello_take.frame_count, len(sk.SEGMENTS), 3)
    assert len(hello_take.angles) == 165
    assert len(sk.SEGMENTS) == 55


def test_timebase_is_thirty_fps_in_seconds(hello_take):
    assert hello_take.times[0] == 0.0
    assert 29.0 < hello_take.source_fps < 31.0
    assert 2.0 < hello_take.duration < 6.0


def test_positions_are_metres_y_up(hello_take):
    # A standing performer: pelvis near a metre, head above it, feet near the floor.
    pelvis_y = hello_take.pos("Pelvis")[:, 1].mean()
    head_y = hello_take.pos("Head")[:, 1].mean()
    foot_y = hello_take.pos("LeftFoot")[:, 1].mean()
    assert 0.7 < pelvis_y < 1.3
    assert head_y > pelvis_y
    assert foot_y < 0.3


def test_skeleton_is_rigid(hello_take):
    """Bone lengths must be constant - the whole reconstruction depends on it."""
    for bone in sk.BONES:
        if bone.tail is None:
            continue
        d = np.linalg.norm(
            hello_take.pos(bone.tail) - hello_take.pos(bone.head), axis=1
        )
        assert d.std() < 1e-3, f"{bone.name} length varies by {d.std() * 1000:.2f}mm"


def test_measured_lengths_are_anatomically_plausible(hello_take):
    m = measure_skeleton(hello_take)
    assert 0.2 < m["LeftUpperArm"] < 0.45
    assert 0.2 < m["LeftForeArm"] < 0.40
    assert abs(m["LeftUpperArm"] - m["RightUpperArm"]) < 0.02
    assert 0.7 < m["_hip_height"] < 1.3


def test_rejects_a_file_that_is_not_this_export(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Timestamp,Foo_position_x\n0,1.0\n")
    with pytest.raises(RokokoFormatError, match="column set does not match"):
        parse_csv(bad)


def test_rejects_a_missing_timestamp_column(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Frame,Foo\n0,1.0\n")
    with pytest.raises(RokokoFormatError, match="Timestamp"):
        parse_csv(bad)
