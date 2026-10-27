"""The avatar's rest pose, exported once from the Unity Editor.

Retargeting needs to know where the avatar's bones point when it is standing in its rest pose.
That is the only thing the backend cannot derive from the motion data itself, so it is exported
from Unity by Editor/RigProfileExporter.cs and uploaded once per avatar.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from . import skeleton as sk


class RigProfileError(ValueError):
    pass


@dataclass(frozen=True)
class RigBone:
    name: str
    humanoid_parent: str | None
    rest_rotation: Rotation          # global, rest pose
    rest_position: np.ndarray        # global, rest pose (3,)
    rest_parent_rotation: Rotation   # global rest rotation of the actual Transform.parent


@dataclass(frozen=True)
class RigProfile:
    avatar_name: str
    hip_height: float
    bones: dict[str, RigBone]
    digest: str

    def rest_axis(self, unity_bone: str) -> np.ndarray:
        """Unit direction the bone points in the avatar's rest pose, in world space."""
        child = sk.REST_AXIS_CHILD.get(unity_bone)
        if child is None or child not in self.bones:
            # Terminal or absent child: fall back to the bone's own rest orientation Y axis,
            # which is the convention Unity's humanoid rigs use for bone direction.
            return self.bones[unity_bone].rest_rotation.apply([0.0, 1.0, 0.0])
        delta = self.bones[child].rest_position - self.bones[unity_bone].rest_position
        n = float(np.linalg.norm(delta))
        if n < 1e-9:
            raise RigProfileError(f"{unity_bone} and {child} share a rest position.")
        return delta / n

    def frame_reference(self, unity_bone: str) -> np.ndarray:
        a, b = sk.FRAME_REF[unity_bone]
        for name in (a, b):
            if name not in self.bones:
                raise RigProfileError(
                    f"rig profile is missing {name!r}, needed to orient {unity_bone}. "
                    "The avatar must be a fully mapped Mecanim Humanoid including fingers."
                )
        return self.bones[b].rest_position - self.bones[a].rest_position

    def nearest_driven_ancestor(self, unity_bone: str) -> str | None:
        driven = set(sk.UNITY_BONES)
        cur = self.bones[unity_bone].humanoid_parent
        while cur is not None:
            if cur in driven:
                return cur
            cur = self.bones[cur].humanoid_parent if cur in self.bones else None
        return None


def load(path: str | Path) -> RigProfile:
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    return from_dict(data, digest=hashlib.sha256(raw).hexdigest()[:16])


def from_dict(data: dict, digest: str | None = None) -> RigProfile:
    if "bones" not in data:
        raise RigProfileError("rig profile has no 'bones' object.")

    bones: dict[str, RigBone] = {}
    for name, b in data["bones"].items():
        bones[name] = RigBone(
            name=name,
            humanoid_parent=b.get("humanoidParent"),
            rest_rotation=Rotation.from_quat(b["restRotation"]),          # [x, y, z, w]
            rest_position=np.asarray(b["restPosition"], dtype=np.float64),
            rest_parent_rotation=Rotation.from_quat(
                b.get("restParentRotation", [0.0, 0.0, 0.0, 1.0])
            ),
        )

    required = set(sk.UNITY_BONES) | {"Head", "LeftFoot", "RightFoot"}
    missing = sorted(required - bones.keys())
    if missing:
        raise RigProfileError(
            f"rig profile is missing {len(missing)} required bones, e.g. {missing[:8]}. "
            "Check that the avatar is configured as Humanoid with all finger bones mapped."
        )

    if digest is None:
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()[:16]

    return RigProfile(
        avatar_name=data.get("avatarName", "unknown"),
        hip_height=float(data.get("hipHeight", bones["Hips"].rest_position[1])),
        bones=bones,
        digest=digest,
    )
