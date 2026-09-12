from types import SimpleNamespace
import json
from pathlib import Path
import struct

import numpy as np
import pytest

from app.ingest import fbx
from app.ingest.landmarks import ARKIT_BLENDSHAPES


class Vec:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z


def matrix(position):
    return SimpleNamespace(
        c0=Vec(1, 0, 0), c1=Vec(0, 1, 0), c2=Vec(0, 0, 1), c3=Vec(*position),
    )


class Channel:
    def __init__(self, name, weight):
        self.name, self.weight = name, weight

    def evaluate_blend_weight(self, _anim, _time):
        return self.weight


def fake_rokoko_scene():
    nodes = []
    for ordinal, name in enumerate(sorted(fbx.REQUIRED_BONES)):
        side = -1 if name.startswith("Left") else 1
        position = [side * 0.2, 1.0 + ordinal * 0.002, 0.0]
        if "Hand" in name:
            joint = int(name[-1]) if name[-1].isdigit() else 0
            position = [side * (0.3 + joint * 0.03), 1.2 + ordinal * 0.0001, 0.0]
        if name == "Head":
            position = [0.0, 1.7, 0.0]
        nodes.append(SimpleNamespace(name=f"mixamorig:{name}", node_to_world=matrix(position)))
    channels = [Channel(f"Face.{name}", index + 1) for index, name in enumerate(ARKIT_BLENDSHAPES)]
    stack = SimpleNamespace(time_begin=2.0, time_end=2.0 + 2 / 60, anim=object())
    return SimpleNamespace(
        settings=SimpleNamespace(frames_per_second=60.0), nodes=nodes,
        blend_channels=channels, anim_stacks=[stack],
    )


def fake_module(scene):
    return SimpleNamespace(
        axes_left_handed_y_up=object(),
        SpaceConversion=SimpleNamespace(ADJUST_TRANSFORMS=object()),
        load_file=lambda *_args, **_kwargs: scene,
        evaluate_scene=lambda source, _anim, _time: source,
    )


def test_combined_fbx_becomes_synchronized_body_hand_and_face_motion(monkeypatch, tmp_path):
    scene = fake_rokoko_scene()
    monkeypatch.setattr(fbx, "ufbx", fake_module(scene))

    take = fbx.parse_fbx(tmp_path / "hello_01.fbx")

    assert take.fps == 60
    assert take.frame_count == 3
    assert take.pose.shape == (3, 33, 3)
    assert take.left_hand.shape == take.right_hand.shape == (3, 21, 3)
    assert take.face_blendshapes.shape == (3, 52)
    assert np.allclose(take.face_blendshapes[0], np.arange(1, 53) / 100)
    assert np.allclose((take.pose[:, 23] + take.pose[:, 24]) / 2, 0)


def test_combined_fbx_requires_every_arkit_expression(monkeypatch, tmp_path):
    scene = fake_rokoko_scene()
    scene.blend_channels.pop()
    monkeypatch.setattr(fbx, "ufbx", fake_module(scene))

    with pytest.raises(fbx.FbxFormatError, match="face capture is incomplete"):
        fbx.parse_fbx(tmp_path / "hello.fbx")


def test_single_checked_in_avatar_maps_every_captured_expression():
    avatar = Path(__file__).parents[2] / (
        "SignoraAvatarTracking/Assets/Models/Avaturn/SignoraNewAvatar.glb"
    )
    encoded = avatar.read_bytes()
    json_length, chunk_type = struct.unpack_from("<II", encoded, 12)
    assert encoded[:4] == b"glTF" and chunk_type == 0x4E4F534A
    document = json.loads(encoded[20:20 + json_length])
    targets = {
        name
        for mesh in document.get("meshes", [])
        for name in mesh.get("extras", {}).get("targetNames", [])
    }
    assert set(ARKIT_BLENDSHAPES) <= targets
