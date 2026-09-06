from types import SimpleNamespace

from app.services import live_motion_service as live
from app.services.translate_service import PlaylistItem


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
