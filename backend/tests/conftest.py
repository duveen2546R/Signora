import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def hello_take():
    from app.ingest.rokoko import parse_csv
    return parse_csv(FIXTURES / "hello.csv")


@pytest.fixture(scope="session")
def library(hello_take):
    """Repository-contained takes with deterministic seam/contact edge cases.

    One checked-in capture supplies anatomically valid motion. Reversed and held variants preserve
    every bone measurement while creating distinct entry and exit behavior; Father contains an
    internal hold, and ThankYou has a corrupt translated tail. Real Rokoko exports remain useful for
    manual evaluation, but CI never skips the core blending suite when they are absent.
    """
    import numpy as np

    from app.ingest.landmarks import LandmarkTake, to_landmarks

    base = to_landmarks(hello_take)

    def variant(name, reverse=False, hold=False, corrupt=False, arm_angle_degrees=0.0):
        def convert(track):
            out = track[::-1].copy() if reverse else track.copy()
            if hold:
                middle = len(out) // 2
                out = np.concatenate([out[:middle], np.repeat(out[middle:middle + 1], 15, axis=0),
                                      out[middle:]], axis=0)
            # Explicit rest bookends guarantee preparation/retraction without inventing any new
            # skeleton geometry. They also make the synthetic sentence shorter after segmentation.
            out = np.concatenate([
                np.repeat(out[:1], 18, axis=0), out, np.repeat(out[-1:], 18, axis=0),
            ], axis=0)
            return out

        take = LandmarkTake(
            name, base.fps, convert(base.pose), convert(base.left_hand), convert(base.right_hand),
        )
        if arm_angle_degrees:
            from app.ingest.blend import GeneralisedPose, Pose, decompose, rebuild
            from app.ingest.landmarks import LandmarkSkeleton

            skel = LandmarkSkeleton.from_takes(base)
            angle = np.deg2rad(arm_angle_degrees)
            rotation = np.array([
                [np.cos(angle), 0.0, np.sin(angle)],
                [0.0, 1.0, 0.0],
                [-np.sin(angle), 0.0, np.cos(angle)],
            ])
            frames = []
            for i in range(take.frame_count):
                gp = decompose(skel, Pose.at(take, i))
                frames.append(rebuild(skel, GeneralisedPose(
                    hip_axis=gp.hip_axis, shoulders=gp.shoulders,
                    head_rotation=gp.head_rotation, head_centroid=gp.head_centroid, legs=gp.legs,
                    arm_dirs=gp.arm_dirs @ rotation.T,
                    left_dirs=gp.left_dirs @ rotation.T,
                    right_dirs=gp.right_dirs @ rotation.T,
                )))
            take = LandmarkTake(
                name, take.fps,
                np.stack([frame.pose for frame in frames]),
                np.stack([frame.left_hand for frame in frames]),
                np.stack([frame.right_hand for frame in frames]),
            )
        if corrupt:
            offset = np.array([0.10, 0.10, 0.10])
            take = LandmarkTake(
                name, take.fps,
                np.concatenate([take.pose, take.pose[-1:] + offset]),
                np.concatenate([take.left_hand, take.left_hand[-1:] + offset]),
                np.concatenate([take.right_hand, take.right_hand[-1:] + offset]),
            )
        return take

    return {
        "Hello": variant("Hello"),
        "ThankYou": variant("ThankYou", reverse=True, corrupt=True, arm_angle_degrees=55.0),
        "Father": variant("Father", hold=True, arm_angle_degrees=-45.0),
    }


@pytest.fixture(scope="session")
def real_library():
    """Optional local recordings for exploratory/manual tests, never required by CI."""
    import glob
    import os

    from app.ingest.landmarks import to_landmarks
    from app.ingest.rokoko import parse_csv

    exports = os.path.expanduser(
        "~/Library/Application Support/com.RokokoElectronics.RokokoStudio/Exports"
    )
    return {
        os.path.basename(path)[:-4]: to_landmarks(parse_csv(path))
        for path in sorted(glob.glob(os.path.join(exports, "*.csv")))
    }


@pytest.fixture(scope="session")
def skeleton(library):
    from app.ingest.landmarks import LandmarkSkeleton
    return LandmarkSkeleton.from_takes(list(library.values()))


@pytest.fixture(scope="session")
def prepared(library, skeleton):
    from app.ingest.compose import prepare
    return {name: prepare(take, skeleton) for name, take in library.items()}
