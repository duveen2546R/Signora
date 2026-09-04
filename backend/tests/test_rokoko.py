"""The parser must agree with the real export, and reject anything else."""
import numpy as np
import pandas as pd
import pytest

from app.ingest import skeleton as sk
from app.ingest.rokoko import (
    RokokoFormatError,
    measure_skeleton,
    parse_csv,
    with_phase_bounds,
)


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


def test_reads_contiguous_phase_labels_and_preserves_the_exclusive_end(tmp_path):
    source = __import__("pathlib").Path(__file__).parent / "fixtures" / "hello.csv"
    frame = pd.read_csv(source)
    frame["Phase"] = "end"
    frame.loc[:9, "Phase"] = "start"
    frame.loc[10:19, "Phase"] = "sign"
    path = tmp_path / "phased.csv"
    frame.to_csv(path, index=False)

    take = parse_csv(path)
    assert take.phase_source == "authored-csv" and take.phase_reviewed
    assert take.sign_start_s == pytest.approx(take.times[10])
    assert take.sign_end_s == pytest.approx(take.times[20])


def test_capture_form_bounds_must_agree_with_csv_labels(tmp_path):
    source = __import__("pathlib").Path(__file__).parent / "fixtures" / "hello.csv"
    frame = pd.read_csv(source)
    frame["Phase"] = "sign"
    path = tmp_path / "phased.csv"
    frame.to_csv(path, index=False)
    take = parse_csv(path)

    with pytest.raises(RokokoFormatError, match="conflict"):
        with_phase_bounds(take, 0.5, 1.0)


@pytest.mark.parametrize(
    ("start", "end"),
    [(0.05, 1.0), (0.5, 0.7), (0.5, 2.65)],
)
def test_reviewed_bounds_require_usable_start_sign_and_end(hello_take, start, end):
    with pytest.raises(RokokoFormatError, match="0.120s of Start"):
        with_phase_bounds(hello_take, start, end)


def test_partial_phase_column_is_rejected(tmp_path):
    source = __import__("pathlib").Path(__file__).parent / "fixtures" / "hello.csv"
    frame = pd.read_csv(source)
    frame["Phase"] = "sign"
    frame.loc[3, "Phase"] = ""
    path = tmp_path / "partial.csv"
    frame.to_csv(path, index=False)
    with pytest.raises(RokokoFormatError, match="every frame"):
        parse_csv(path)
