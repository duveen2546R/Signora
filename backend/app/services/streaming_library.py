"""Offline-published, fixed-skeleton streaming motion units.

Each edge owns its exact boundary state and playback variant. Runtime only reads
verified artifacts; it never calls prepare/compose/plan_transition.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from functools import lru_cache

import numpy as np

from app.core.config import settings
from app.ingest import blend
from app.ingest.compose import ALGORITHM_VERSION, TARGET_FPS, compose, prepare, neutral_pose, _hold
from app.ingest.landmarks import LandmarkSkeleton, LandmarkTake, slice_frames
from app.services.compose_service import ComposeError, _raw, landmark_path, _pace_reviewed
from app.services.artifact_paths import source_file
from app.services.live_motion_service import canonical_clips, library_version, _slice_payload, _sign_segments
from app.models import LiveMotionArtifact

FORMAT_VERSION = 3


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def directory():
    return settings.transition_dir / "streaming"


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, separators=(",", ":")))
    temporary.replace(path)


def context(session):
    path = directory() / "skeleton.json"
    if path.exists():
        return json.loads(path.read_text())
    takes = []
    for clip in canonical_clips(session):
        source = str(source_file(clip.source_csv)) if clip.source_csv else ""
        takes.append(_raw(str(landmark_path(clip)), source, clip.content_hash))
    if not takes:
        raise ComposeError("No canonical recordings")
    skeleton = LandmarkSkeleton.from_takes(takes)
    prepared = [prepare(take, skeleton) for take in takes]
    rest = neutral_pose(skeleton, prepared)
    value = {
        "head": skeleton.head_shape.tolist(), "hip": skeleton.hip_half_width,
        "poseLengths": [[*edge, length] for edge, length in skeleton.pose_lengths.items()],
        "handLengths": [[*edge, length] for edge, length in skeleton.hand_lengths.items()],
        "neutral": {"pose": rest.pose.tolist(), "leftHand": rest.left_hand.tolist(), "rightHand": rest.right_hand.tolist()},
    }
    write_json(path, value)
    return value


def hydrate(value):
    skeleton = LandmarkSkeleton(np.asarray(value["head"]), value["hip"],
                                {(a, b): length for a, b, length in value["poseLengths"]},
                                {(a, b): length for a, b, length in value["handLengths"]})
    rest = blend.Pose(*(np.asarray(value["neutral"][key]) for key in ("pose", "leftHand", "rightHand")))
    return skeleton, rest


def artifact_key(snapshot, clips, rate, boundary):
    return digest([FORMAT_VERSION, ALGORITHM_VERSION, digest(snapshot), rate, boundary,
                   [[clip.content_hash, (clip.qc or {}).get("phases", {})] for clip in clips]])


def _save(key, payload):
    path = directory() / f"{key}.json.gz"
    temporary = path.with_suffix(".tmp")
    with gzip.open(temporary, "wt") as target:
        json.dump(payload, target, separators=(",", ":"))
    temporary.replace(path)
    return {"key": key, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size, "status": "ready"}


@lru_cache(maxsize=48)
def read_artifact(key, sha):
    path = directory() / f"{key}.json.gz"
    encoded = path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != sha:
        raise ComposeError("Streaming motion artifact checksum failed; recompile library")
    payload = json.loads(gzip.decompress(encoded))
    if payload.get("blendQuality", {}).get("status") != "direct":
        raise ComposeError("Unvalidated streaming artifact")
    return payload


def manifest():
    path = directory() / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _format_is_current(value):
    # Early test/development manifests had no explicit format field. Published v2 manifests do,
    # and must be rebuilt so body-only artifacts cannot masquerade as face-capable motion.
    return value.get("formatVersion", FORMAT_VERSION) == FORMAT_VERSION


def readiness(session):
    value = manifest()
    current = library_version(session)
    if (not value or not value.get("complete") or value.get("libraryVersion") != current
            or not _format_is_current(value)):
        return {"published": False, "warm": False, "error": "Run compile_live_library.py --streaming first.",
                "latencyVerified": False}
    entries = list(value["artifacts"].values())
    return {"published": True, "warm": value.get("publicationVersion") in _warmed,
            "publicationVersion": value.get("publicationVersion"),
            "libraryVersion": current, "skeletonDigest": value["skeletonDigest"],
            "compiled": sum(entry["status"] == "ready" for entry in entries), "required": len(entries),
            "failed": [{"unit": key, "error": entry["error"]} for key, entry in value["artifacts"].items() if entry["status"] != "ready"],
            "durations": value["durations"], "latencyVerified": False}


_warmed = set()


def warm(session):
    value = manifest()
    if (not value or not value.get("complete") or value["libraryVersion"] != library_version(session)
            or not _format_is_current(value)):
        raise ComposeError("Publish the streaming motion library before listening")
    # Verify compressed files before accepting audio. Decoded LRU stays bounded; no geometry work.
    for entry in value["artifacts"].values():
        if entry["status"] == "ready":
            data = (directory() / f"{entry['key']}.json.gz").read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ComposeError("Streaming artifact changed since publication")
    _warmed.add(value["publicationVersion"])
    return readiness(session)


def part(value, name):
    entry = value["artifacts"].get(name)
    if not entry or entry["status"] != "ready":
        raise ComposeError(f"No validated streaming motion for {name}")
    return read_artifact(entry["key"], entry["sha256"])


def assemble(session, items, tail, boundary, rate, version):
    value = manifest()
    if (not value or not value.get("complete") or value["libraryVersion"] != version
            or not _format_is_current(value)):
        raise ComposeError("Streaming library is stale or unpublished")
    output = []
    previous = tail
    for occurrence, item in enumerate(items):
        prefix = f"{rate}:"
        name = prefix + (f"open:{item.clip_id}" if previous is None else f"{boundary}:{previous}:{item.clip_id}")
        try:
            motion = part(value, name)
        except ComposeError:
            if previous is None:
                raise
            from app.services.live_motion_service import _join_payloads
            closure = part(value, prefix + f"close-{boundary}:{previous}")
            opening = part(value, prefix + f"open:{item.clip_id}")
            motion = _join_payloads([closure, opening], closure["blendQuality"].get("seams", []) + opening["blendQuality"].get("seams", []))
            motion["warnings"] = ["Directed edge unavailable; using a validated neutral rest."]
        output.append(_slice_payload(motion, 0, motion["frameCount"], occurrence))
        previous, boundary = item.clip_id, "flow"
    from app.services.live_motion_service import _join_payloads
    joined = _join_payloads(output, [seam for motion in output for seam in motion["blendQuality"].get("seams", [])])
    joined["maxPlaybackRate"] = 1.0  # Mechanical headroom alone is not permission to accelerate signs.
    joined["streamingLibrary"] = True
    joined["startsFromNeutral"] = tail is None
    joined["playbackVariant"] = rate
    joined["warnings"] = [warning for motion in output for warning in motion.get("warnings", [])]
    return joined, previous, True


def close(session, tail, boundary, rate, version):
    value = manifest()
    if (not value or not value.get("complete") or value["libraryVersion"] != version
            or not _format_is_current(value)):
        raise ComposeError("Streaming library is stale or unpublished")
    return part(value, f"{rate}:close-{boundary}:{tail}"), True


def select_rate(items, target_ms):
    """Only change variants at neutral. Never retime an active/protected stroke."""
    value = manifest() or {"artifacts": {}}
    estimates = {}
    for rate in (1.0, 0.8):
        try:
            total = 0
            for item in items:
                motion = part(value, f"{rate}:open:{item.clip_id}")
                part(value, f"{rate}:close-flow:{item.clip_id}")
                total += motion["frameCount"] / motion["fps"] * 1000
            estimates[rate] = total
        except ComposeError:
            continue
    if 0.8 in estimates and (1.0 not in estimates or estimates[0.8] <= target_ms):
        return 0.8
    return 1.0


def compile_library(session, limit=0, retry_failed=False):
    directory().mkdir(parents=True, exist_ok=True)
    snapshot = context(session)
    skel, rest = hydrate(snapshot)
    clips = canonical_clips(session)
    old = manifest() or {"artifacts": {}}
    old_by_key = {entry["key"]: entry for entry in old["artifacts"].values()}
    value = {"libraryVersion": library_version(session), "formatVersion": FORMAT_VERSION,
             "skeletonDigest": digest(snapshot), "artifacts": {}, "durations": {}}
    prepared = {}
    singles = {}
    built = 0

    def take(clip, rate):
        key = (clip.id, rate)
        if key not in prepared:
            source = str(source_file(clip.source_csv)) if clip.source_csv else ""
            raw = _raw(str(landmark_path(clip)), source, clip.content_hash)
            if not raw.phase_reviewed:
                raise ComposeError(f"{clip.gloss.name}: review phase boundaries first")
            result = prepare(raw, skel)
            prepared[key] = result if rate == 1.0 else _pace_reviewed(result, skel)
        return prepared[key]

    def build(name, participants, rate, make):
        nonlocal built
        key = artifact_key(snapshot, participants, rate, name.split(":", 1)[1].split(":")[0])
        entry = old_by_key.get(key)
        row = session.get(LiveMotionArtifact, key)
        if row is not None:
            entry = (row.quality or {}).get("artifactRecord", entry)
        if entry and entry["status"] == "ready":
            try:
                read_artifact(key, entry["sha256"])
            except (OSError, ValueError, ComposeError):
                entry = None
        if entry and (entry["status"] == "ready" or entry["status"] == "failed" and not retry_failed):
            value["artifacts"][name] = entry
            return
        if limit and built >= limit:
            value["artifacts"][name] = {"key": key, "status": "pending", "error": "Compilation limit reached"}
            return
        try:
            payload = make()
            payload["maxPlaybackRate"] = 1.0
            payload["streamingLibrary"] = True
            payload["playbackVariant"] = rate
            payload["neutral"] = snapshot["neutral"]
            value["artifacts"][name] = _save(key, payload)
        except (ValueError, ComposeError) as exc:
            value["artifacts"][name] = {"key": key, "status": "failed", "error": str(exc)}
        entry = value["artifacts"][name]
        session.merge(LiveMotionArtifact(key=key, library_version=value["libraryVersion"],
            from_clip_hash=participants[0].content_hash if len(participants) > 1 else "",
            to_clip_hash=participants[-1].content_hash, algorithm_version=ALGORITHM_VERSION,
            status=entry["status"], artifact_path=str(directory() / f"{key}.json.gz") if entry["status"] == "ready" else "",
            quality={"artifactRecord": entry, "skeletonDigest": digest(snapshot), "rate": rate, "unit": name},
            error=entry.get("error", "")))
        session.commit()
        built += 1
        print(f"{value['artifacts'][name]['status']:7} {name}", flush=True)
        # Checkpoint after each job, including rejected jobs. No partially written artifacts.
        write_json(directory() / "compilation.json", value)

    def complete(participants, rate):
        key = (participants[0].id, rate)
        if len(participants) == 1 and key in singles:
            return singles[key]
        result = compose(skel, [(clip.gloss.name, take(clip, rate)) for clip in participants], rest=rest).to_payload()
        if len(participants) == 1:
            singles[key] = result
        return result

    def single_section(clip, rate, kind):
        if kind in {"body", "open"}:
            from app.ingest.segment import find_phases
            from app.ingest.landmarks import concat
            track = take(clip, rate)
            phase = find_phases(track)
            if kind == "body":
                result = slice_frames(track, phase.stroke_start, phase.stroke_end).to_payload()
                result["segments"] = [{"kind": "sign", "gloss": clip.gloss.name, "occurrenceIndex": 0,
                                       "startFrame": 0, "endFrame": result["frameCount"]}]
                result["blendQuality"] = {"status": "direct", "seams": []}
                return result
            # Search only the non-semantic run-up. A shorter entry must pass the
            # same seam tests; the protected sign is copied unchanged.
            neutral = LandmarkTake("neutral", TARGET_FPS, np.repeat(rest.pose[None], 4, axis=0),
                np.repeat(rest.left_hand[None], 4, axis=0), np.repeat(rest.right_hand[None], 4, axis=0))
            best = None
            for index in sorted(set(range(phase.stroke_start, -1, -3)) | {0}):
                edge = blend.plan_transition(skel, neutral, 3, track, index, TARGET_FPS)
                if edge.quality.passed:
                    cost = edge.track.frame_count + phase.stroke_start - index
                    if best is None or cost < best[0]:
                        best = (cost, index, edge)
            if best is None:
                raise ComposeError(f"No validated neutral entry to {clip.gloss.name}")
            _, index, edge = best
            target = slice_frames(track, index, phase.stroke_end)
            result = concat([edge.track, target]).to_payload()
            cursor = edge.track.frame_count
            segments = [{"kind": "transition", "gloss": "", "startFrame": 0, "endFrame": cursor}]
            if index < phase.stroke_start:
                end = cursor + phase.stroke_start - index
                segments.append({"kind": "preparation", "gloss": clip.gloss.name, "startFrame": cursor, "endFrame": end})
                cursor = end
            segments.append({"kind": "sign", "gloss": clip.gloss.name, "occurrenceIndex": 0,
                             "startFrame": cursor, "endFrame": result["frameCount"]})
            result["segments"] = segments
            result["blendQuality"] = {"status": "direct", "seams": [edge.quality.as_dict()]}
            return result
        full = complete([clip], rate)
        sign = _sign_segments(full)[0]
        bounds = {"body": (sign["startFrame"], sign["endFrame"]),
                  "open": (0, sign["endFrame"]),
                  "close-flow": (sign["endFrame"], full["frameCount"])}[kind]
        return _slice_payload(full, *bounds, 0 if kind != "close-flow" else None)

    def flow(left, right, rate):
        full = complete([left, right], rate)
        signs = _sign_segments(full)
        for clip, sign in zip((left, right), signs, strict=True):
            body = part(value, f"{rate}:body:{clip.id}")
            for channel in ("pose", "leftHand", "rightHand", "faceBlendshapes"):
                if not np.array_equal(full[channel][sign["startFrame"]:sign["endFrame"]], body[channel]):
                    raise ComposeError("Pair changed protected body; refusing incompatible boundary")
        return _slice_payload(full, signs[0]["endFrame"], signs[1]["endFrame"], 0)

    def held(left, right, rate):
        source = LandmarkTake.from_payload(part(value, f"{rate}:body:{left.id}"))
        source = _hold(source, source.frame_count - 1, 4, TARGET_FPS)
        if right is None:
            target = LandmarkTake("neutral", TARGET_FPS, rest.pose[None], rest.left_hand[None], rest.right_hand[None])
        else:
            target = LandmarkTake.from_payload(part(value, f"{rate}:body:{right.id}"))
        bridge = blend.plan_transition(skel, source, source.frame_count - 1, target, 0, TARGET_FPS)
        tail_segments = None
        # A held hand may be too far from neutral for a direct edge. Rejoin the
        # authored retraction instead, never extrapolating through the torso.
        if right is None and not bridge.quality.passed:
            closure = part(value, f"{rate}:close-flow:{left.id}")
            retraction = LandmarkTake.from_payload(closure)
            for index in range(0, min(retraction.frame_count - 1, 31), 3):
                candidate = blend.plan_transition(skel, source, source.frame_count - 1, retraction, index, TARGET_FPS)
                if candidate.quality.passed:
                    bridge = candidate
                    tail = _slice_payload(closure, index, closure["frameCount"], None)
                    target = LandmarkTake.from_payload(tail)
                    tail_segments = tail["segments"]
                    break
        if not bridge.quality.passed:
            raise ComposeError("Held-pose transition rejected: " + "; ".join(bridge.quality.reasons))
        from app.ingest.landmarks import concat
        track = concat([bridge.track, target])
        result = track.to_payload()
        cursor = bridge.track.frame_count
        result["segments"] = [{"kind": "transition", "gloss": "", "startFrame": 0, "endFrame": cursor},
                              {"kind": "sign" if right else "hold", "gloss": right.gloss.name if right else "",
                               "startFrame": cursor, "endFrame": track.frame_count, "occurrenceIndex": 0}]
        if tail_segments is not None:
            result["segments"] = result["segments"][:1] + [{**segment,
                "startFrame": segment["startFrame"] + cursor, "endFrame": segment["endFrame"] + cursor} for segment in tail_segments]
        result["blendQuality"] = {"status": "direct", "seams": [bridge.quality.as_dict()]}
        return result

    for rate in (1.0, 0.8):
        for clip in clips:
            for kind in ("body", "open", "close-flow"):
                build(f"{rate}:{kind}:{clip.id}", [clip], rate, lambda c=clip, r=rate, k=kind: single_section(c, r, k))
            build(f"{rate}:close-held:{clip.id}", [clip], rate, lambda c=clip, r=rate: held(c, None, r))
            try:
                body = part(value, f"{rate}:body:{clip.id}")
                opening = part(value, f"{rate}:open:{clip.id}")
                value["durations"][f"{rate}:{clip.gloss.name}"] = {
                    "signMs": body["frameCount"] / body["fps"] * 1000,
                    "entryMs": _sign_segments(opening)[0]["startFrame"] / opening["fps"] * 1000,
                }
            except ComposeError:
                pass
        for left in clips:
            for right in clips:
                build(f"{rate}:flow:{left.id}:{right.id}", [left, right], rate, lambda a=left, b=right, r=rate: flow(a, b, r))
                build(f"{rate}:held:{left.id}:{right.id}", [left, right], rate, lambda a=left, b=right, r=rate: held(a, b, r))
    value["complete"] = not any(entry["status"] == "pending" for entry in value["artifacts"].values())
    value["publicationVersion"] = digest([FORMAT_VERSION, value["skeletonDigest"],
        sorted((name, entry["key"], entry["status"], entry.get("sha256")) for name, entry in value["artifacts"].items())])
    write_json(directory() / ("manifest.json" if value["complete"] else "compilation.json"), value)
    _warmed.clear()
    return value
