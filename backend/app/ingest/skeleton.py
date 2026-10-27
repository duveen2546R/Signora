"""Canonical description of the Rokoko biomechanics skeleton and its mapping to Unity Humanoid.

The source CSV (Rokoko Studio "biomechanics" export) carries, per frame:
  * world joint-center positions in metres, Y-up, LEFT-handed (Unity-style) for 55 segments
  * three anatomical angle channels in degrees for 55 joints

It carries no rotations, so bone orientations are reconstructed geometrically (see reconstruct.py).
This module is the single place where Rokoko's naming and hierarchy are written down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SIDES = ("Left", "Right")
# Rokoko digit index -> Unity Humanoid finger name.
DIGITS = {1: "Thumb", 2: "Index", 3: "Middle", 4: "Ring", 5: "Little"}

# Rokoko spells the proximal phalanx with a stray 'g'. Preserved deliberately: it must match the file.
PROXIMAL = "ProximalPhalangx"
INTERMEDIATE = "IntermediatePhalanx"
DISTAL = "DistalPhalanx"


def _digit(side: str, n: int, part: str) -> str:
    return f"{side}Digit{n}{part}"


# --- Segments that carry a *_position_{x,y,z} triple -------------------------------------------

def _all_segments() -> list[str]:
    segs = [
        "Pelvis", "Chest", "Head",
        *[f"{s}{p}" for s in SIDES for p in ("UpperLeg", "LowerLeg", "Foot")],
        *[f"{s}{p}" for s in SIDES for p in ("Shoulder", "UpperArm", "ForeArm", "Hand")],
    ]
    for side in SIDES:
        for n in DIGITS:
            parts = ["MetaCarpal", PROXIMAL] + ([] if n == 1 else [INTERMEDIATE]) + [DISTAL]
            segs += [_digit(side, n, p) for p in parts]
    return segs


SEGMENTS: tuple[str, ...] = tuple(_all_segments())

# --- Joints that carry three angle channels ----------------------------------------------------
# Values are the exact channel suffixes, in file order: (sagittal, frontal, axial).
JOINT_CHANNELS: dict[str, tuple[str, str, str]] = {
    "Pelvis": ("extension", "lateral_flexion_rotation", "axial_rotation"),
    "Thorax": ("extension", "lateral_flexion_rotation", "axial_rotation"),
    "Neck": ("flexion", "left-ward_tilt", "right-ward_rotation"),
    **{f"{s}Hip": ("flexion", "adduction", "external_rotation") for s in SIDES},
    **{f"{s}Knee": ("flexion", "adduction", "external_rotation") for s in SIDES},
    **{f"{s}Ankle": ("dorsiflexion", "inversion", "internal_rotation") for s in SIDES},
    **{f"{s}Shoulder": ("flexion", "abduction", "external_rotation") for s in SIDES},
    **{f"{s}Scapula": ("protraction", "medial_rotation", "posterior_tilt") for s in SIDES},
    **{f"{s}Elbow": ("flexion", "abduction", "pronation") for s in SIDES},
    **{f"{s}Wrist": ("flexion", "adduction", "pronation") for s in SIDES},
}
_FINGER_JOINT = ("flexion", "ulnarDeviation", "pronation")
for _side in SIDES:
    for _n in DIGITS:
        _names = (
            ["Carpometacarpal", "Metacarpophalangeal", "Interphalangeal"] if _n == 1
            else ["Carpometacarpal", "Metacarpophalangeal",
                  "ProximalInterphalangeal", "DistalInterphalangeal"]
        )
        for _nm in _names:
            JOINT_CHANNELS[_digit(_side, _n, _nm)] = _FINGER_JOINT


def position_columns() -> list[str]:
    return [f"{seg}_position_{ax}" for seg in SEGMENTS for ax in "xyz"]


def angle_columns() -> list[str]:
    return [f"{j}_{ch}" for j, chs in JOINT_CHANNELS.items() for ch in chs]


# --- Bones -------------------------------------------------------------------------------------

TwistKind = Literal["frame", "channel", "zero"]


@dataclass(frozen=True)
class Bone:
    """One drivable bone.

    `head`/`tail` are the segment names whose positions define the bone's direction.
    `unity` is the Unity HumanBodyBones value it drives.

    Roll about the bone axis is not observable from a single direction, so each bone declares how to
    recover it:
      * "frame"   - a second, independent axis is observable from `ref_a`->`ref_b`, giving a full
                    orthonormal orientation from geometry alone. Used where it matters most and is
                    available: pelvis, spine and both hands.
      * "channel" - take roll from a clinical angle channel (`twist_channel`, degrees).
      * "zero"    - roll is negligible and noisy (finger bones); leave it out.
    """

    name: str
    head: str
    tail: str | None          # None => terminal bone, no observable direction
    unity: str
    twist: TwistKind = "zero"
    twist_channel: str | None = None
    ref_a: str | None = None
    ref_b: str | None = None
    # Terminal bones only: bend angle channel applied relative to the parent bone.
    terminal_channel: str | None = None


def _arm_bones(side: str) -> list[Bone]:
    o = "Right" if side == "Left" else "Left"  # noqa: F841  (kept for symmetry/readability)
    return [
        Bone(f"{side}Shoulder", f"{side}Shoulder", f"{side}UpperArm", f"{side}Shoulder",
             twist="channel", twist_channel=f"{side}Scapula_medial_rotation"),
        Bone(f"{side}UpperArm", f"{side}UpperArm", f"{side}ForeArm", f"{side}UpperArm",
             twist="channel", twist_channel=f"{side}Shoulder_external_rotation"),
        Bone(f"{side}ForeArm", f"{side}ForeArm", f"{side}Hand", f"{side}LowerArm",
             twist="channel", twist_channel=f"{side}Elbow_pronation"),
        # Palm orientation is a core phonological parameter of a sign, and it is fully observable
        # from the knuckle spread - so take it from geometry rather than a clinical channel.
        # Note the reference points are the proximal phalanges (the knuckles), not the metacarpals:
        # a metacarpal's origin sits back at the wrist, which would give a short, ill-conditioned
        # axis and would not correspond to Unity's Index/Little Proximal bones.
        Bone(f"{side}Hand", f"{side}Hand", _digit(side, 3, PROXIMAL), f"{side}Hand",
             twist="frame", ref_a=_digit(side, 2, PROXIMAL), ref_b=_digit(side, 5, PROXIMAL)),
    ]


def _leg_bones(side: str) -> list[Bone]:
    return [
        Bone(f"{side}UpperLeg", f"{side}UpperLeg", f"{side}LowerLeg", f"{side}UpperLeg",
             twist="channel", twist_channel=f"{side}Hip_external_rotation"),
        Bone(f"{side}LowerLeg", f"{side}LowerLeg", f"{side}Foot", f"{side}LowerLeg",
             twist="channel", twist_channel=f"{side}Knee_external_rotation"),
    ]


def _finger_bones(side: str) -> list[Bone]:
    out: list[Bone] = []
    for n, finger in DIGITS.items():
        if n == 1:
            # Unity's ThumbProximal is anatomically the metacarpal.
            chain = [("MetaCarpal", PROXIMAL, "Proximal"),
                     (PROXIMAL, DISTAL, "Intermediate")]
            tip_channel = _digit(side, n, "Interphalangeal") + "_flexion"
        else:
            # Unity has no metacarpal bone for digits 2-5; it lives inside the palm.
            chain = [(PROXIMAL, INTERMEDIATE, "Proximal"),
                     (INTERMEDIATE, DISTAL, "Intermediate")]
            tip_channel = _digit(side, n, "DistalInterphalangeal") + "_flexion"
        for head, tail, unity_part in chain:
            out.append(Bone(
                name=_digit(side, n, unity_part),
                head=_digit(side, n, head), tail=_digit(side, n, tail),
                unity=f"{side}{finger}{unity_part}", twist="zero",
            ))
        out.append(Bone(
            name=_digit(side, n, "Distal"),
            head=_digit(side, n, DISTAL), tail=None,
            unity=f"{side}{finger}Distal", twist="zero", terminal_channel=tip_channel,
        ))
    return out


def _build_bones() -> list[Bone]:
    bones = [
        # Pelvis and chest orientations are fully observable from the hip and shoulder spreads.
        Bone("Hips", "Pelvis", "Chest", "Hips", twist="frame",
             ref_a="LeftUpperLeg", ref_b="RightUpperLeg"),
        Bone("Spine", "Pelvis", "Chest", "Spine", twist="frame",
             ref_a="LeftShoulder", ref_b="RightShoulder"),
        Bone("Neck", "Chest", "Head", "Neck", twist="channel",
             twist_channel="Neck_right-ward_rotation"),
        Bone("Head", "Head", None, "Head", twist="zero", terminal_channel="Neck_flexion"),
    ]
    for side in SIDES:
        bones += _arm_bones(side) + _leg_bones(side) + _finger_bones(side)
    return bones


BONES: tuple[Bone, ...] = tuple(_build_bones())

# Parent Unity bone for each driven bone, used to convert global -> local rotations.
UNITY_PARENT: dict[str, str | None] = {
    "Hips": None, "Spine": "Hips", "Neck": "Spine", "Head": "Neck",
}
for _s in SIDES:
    UNITY_PARENT.update({
        f"{_s}Shoulder": "Spine", f"{_s}UpperArm": f"{_s}Shoulder",
        f"{_s}LowerArm": f"{_s}UpperArm", f"{_s}Hand": f"{_s}LowerArm",
        f"{_s}UpperLeg": "Hips", f"{_s}LowerLeg": f"{_s}UpperLeg",
    })
    for _f in DIGITS.values():
        UNITY_PARENT.update({
            f"{_s}{_f}Proximal": f"{_s}Hand",
            f"{_s}{_f}Intermediate": f"{_s}{_f}Proximal",
            f"{_s}{_f}Distal": f"{_s}{_f}Intermediate",
        })

UNITY_BONES: tuple[str, ...] = tuple(b.unity for b in BONES)


# --- Correspondence between source geometry and the avatar's rest pose -------------------------
# For each driven Unity bone: the Unity bone whose rest position defines this bone's rest direction.
REST_AXIS_CHILD: dict[str, str] = {
    "Hips": "Spine", "Spine": "Neck", "Neck": "Head",
}
for _s in SIDES:
    REST_AXIS_CHILD.update({
        f"{_s}Shoulder": f"{_s}UpperArm",
        f"{_s}UpperArm": f"{_s}LowerArm",
        f"{_s}LowerArm": f"{_s}Hand",
        f"{_s}Hand": f"{_s}MiddleProximal",
        f"{_s}UpperLeg": f"{_s}LowerLeg",
        f"{_s}LowerLeg": f"{_s}Foot",
    })
    for _f in DIGITS.values():
        REST_AXIS_CHILD[f"{_s}{_f}Proximal"] = f"{_s}{_f}Intermediate"
        REST_AXIS_CHILD[f"{_s}{_f}Intermediate"] = f"{_s}{_f}Distal"

# For twist="frame" bones: the pair of Unity bones whose rest positions give the secondary axis.
# These mirror the source references declared on the Bone entries, so the same basis construction
# applies to both sides of the retarget.
FRAME_REF: dict[str, tuple[str, str]] = {
    "Hips": ("LeftUpperLeg", "RightUpperLeg"),
    "Spine": ("LeftShoulder", "RightShoulder"),
    "LeftHand": ("LeftIndexProximal", "LeftLittleProximal"),
    "RightHand": ("RightIndexProximal", "RightLittleProximal"),
}

# Terminal bones bend about their own local X axis by default.
TERMINAL_BEND_AXIS: dict[str, tuple[float, float, float]] = {}
