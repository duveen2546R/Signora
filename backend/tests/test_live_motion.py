from types import SimpleNamespace

import pytest

from app.services import live_motion_service as live
from app.services.translate_service import PlaylistItem
from app.services.compose_service import ComposeError


def frame(value):
    return [[value, 0, 0] for _ in range(33)]


def hand(value):
    return [[value, 0, 0] for _ in range(21)]


def payload(glosses):
    segments = [{"gloss": "", "kind": "hold", "startFrame": 0, "endFrame": 1}]
    seams = []
    cursor = 1
    previous = ""
    for occurrence, gloss in enumerate(glosses):
        segments.append({"gloss": gloss, "kind": "transition", "startFrame": cursor,
                         "endFrame": cursor + 1, "occurrenceIndex": occurrence})
        seams.append({"fromGloss": previous, "toGloss": gloss, "mode": "direct",
                      "passed": True, "score": 90})
        cursor += 1
        segments.append({"gloss": gloss, "kind": "sign", "startFrame": cursor,
                         "endFrame": cursor + 2, "occurrenceIndex": occurrence})
        cursor += 2
        previous = gloss
    segments.append({"gloss": previous, "kind": "retraction", "startFrame": cursor,
                     "endFrame": cursor + 1, "occurrenceIndex": len(glosses) - 1})
    cursor += 1
    segments.append({"gloss": "", "kind": "transition", "startFrame": cursor,
                     "endFrame": cursor + 1})
    seams.append({"fromGloss": previous, "toGloss": "", "mode": "direct",
                  "passed": True, "score": 90})
    cursor += 1
    segments.append({"gloss": "", "kind": "hold", "startFrame": cursor,
                     "endFrame": cursor + 1})
    cursor += 1
    return {
        "fps": 60, "frameCount": cursor,
        "pose": [frame(index) for index in range(cursor)],
        "leftHand": [hand(index) for index in range(cursor)],
        "rightHand": [hand(index) for index in range(cursor)],
        "segments": segments,
        "blendQuality": {"status": "direct", "seams": seams},
    }


def clip(clip_id, gloss):
    return SimpleNamespace(id=clip_id, content_hash=gloss.lower(), is_canonical=True,
                           gloss=SimpleNamespace(name=gloss))


def item(value):
    return PlaylistItem(value.gloss.name, value.id, 1000)


def test_live_assembly_uses_opening_and_pair_edges_without_replaying_previous_sign(monkeypatch):
    hello, father = clip(1, "HELLO"), clip(2, "FATHER")
    monkeypatch.setattr(live, "canonical_clips", lambda _session: [hello, father])
    monkeypatch.setattr(live, "cached_composition",
                        lambda _session, clips, _version: (payload([c.gloss.name for c in clips]), True))
    result, tail, cache_hit = live.assemble_live_motion(
        object(), [item(hello), item(father)], None, "v1",
    )
    assert tail == father.id and cache_hit
    assert [segment["gloss"] for segment in result["segments"] if segment["kind"] == "sign"] == [
        "HELLO", "FATHER",
    ]
    assert result["segments"][0]["startFrame"] == 0
    assert result["segments"][-1]["endFrame"] == result["frameCount"]


def test_continuation_contains_only_the_new_sign(monkeypatch):
    hello, father = clip(1, "HELLO"), clip(2, "FATHER")
    monkeypatch.setattr(live, "canonical_clips", lambda _session: [hello, father])
    monkeypatch.setattr(live, "cached_composition",
                        lambda _session, clips, _version: (payload([c.gloss.name for c in clips]), True))
    result, tail, _ = live.assemble_live_motion(object(), [item(father)], hello.id, "v1")
    signs = [segment for segment in result["segments"] if segment["kind"] == "sign"]
    assert [segment["gloss"] for segment in signs] == ["FATHER"]
    assert signs[0]["occurrenceIndex"] == 0
    assert tail == father.id


def test_close_starts_after_the_sign_and_returns_to_rest(monkeypatch):
    hello = clip(1, "HELLO")
    monkeypatch.setattr(live, "cached_composition",
                        lambda _session, clips, _version: (payload([clips[0].gloss.name]), True))
    session = SimpleNamespace(get=lambda _model, _id: hello)
    result, cache_hit = live.assemble_live_close(session, hello.id, "v1")
    assert cache_hit
    assert not any(segment["kind"] == "sign" for segment in result["segments"])
    assert result["segments"][-1]["kind"] == "hold"
    assert result["segments"][-1]["endFrame"] == result["frameCount"]


def test_cache_miss_never_compiles_on_a_live_request(monkeypatch, tmp_path):
    monkeypatch.setattr(live.settings, "transition_dir", tmp_path)
    monkeypatch.setattr(live, "compose_clips", lambda *_: pytest.fail("runtime must not compile"))
    session = SimpleNamespace(get=lambda *_: None)
    with pytest.raises(ComposeError, match="not compiled"):
        live.cached_composition(session, [clip(1, "HELLO")], "new-version")


def test_decoded_motion_is_reused_and_file_replacement_invalidates_cache(tmp_path):
    import gzip
    import json
    path = tmp_path / "motion.json.gz"
    with gzip.open(path, "wt") as stream:
        json.dump(payload(["HELLO"]), stream)
    live._read_compiled.cache_clear()
    first = live._read_compiled(str(path), 1, 10)
    assert live._read_compiled(str(path), 1, 10) is first
    assert live._read_compiled(str(path), 2, 10) is not first
    assert 1 <= first["maxPlaybackRate"] <= 1.5


def test_high_speed_capture_cannot_be_sped_up():
    track = payload(["HELLO"])
    assert live.playback_rate_limit(track) == 1.0  # fixture moves 1 metre per frame
    for channel in ("pose", "leftHand", "rightHand"):
        track[channel] = [track[channel][0]] * track["frameCount"]
    assert live.playback_rate_limit(track) == 1.5


def test_uncompiled_long_paced_phrase_uses_all_cached_signs_in_order(monkeypatch):
    hello, father = clip(1, "HELLO"), clip(2, "FATHER")
    monkeypatch.setattr(live, "canonical_clips", lambda _: [hello, father])
    def cached(_session, clips, _version):
        if len(clips) > 2:
            raise ComposeError("not compiled")
        value = payload([c.gloss.name for c in clips])
        if len(clips) == 2:
            value["blendQuality"]["playbackRate"] = 0.8
        return value, True
    monkeypatch.setattr(live, "cached_composition", cached)
    result, tail, hit = live.assemble_live_motion(
        object(), [item(hello), item(father), item(hello)], None, "v1",
    )
    assert [s["gloss"] for s in result["segments"] if s["kind"] == "sign"] == ["HELLO", "FATHER", "HELLO"]
    assert tail is None and hit and result["warnings"]
