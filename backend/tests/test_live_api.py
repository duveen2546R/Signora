from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import live
from app.services.translate_service import Interpretation, PlaylistItem


class Session:
    def get(self, _model, _id):
        return SimpleNamespace(is_canonical=True)


def request(**changes):
    values = dict(streamId="stream", sequence=2, text="hello", fromClipId=None,
                  libraryVersion="current")
    values.update(changes)
    return live.LiveTranslateRequest(**values)


def test_stale_library_version_returns_conflict(monkeypatch):
    monkeypatch.setattr(live, "library_version", lambda _session: "current")
    with pytest.raises(HTTPException) as caught:
        live.live_translate(request(libraryVersion="old"), Session())
    assert caught.value.status_code == 409


def test_live_response_echoes_sequence_and_tail(monkeypatch):
    quality = {"status": "direct", "seams": []}
    motion = {"fps": 60, "frameCount": 1, "pose": [], "leftHand": [], "rightHand": [],
              "segments": [], "blendQuality": quality}
    interpretation = Interpretation("preview", 4, "literal-live", [
        PlaylistItem("HELLO", 7, 500),
    ], issues=[{"code": "unreviewed-preview", "message": "Preview."}])
    monkeypatch.setattr(live, "library_version", lambda _session: "current")
    monkeypatch.setattr(live, "interpret_live", lambda *_: interpretation)
    monkeypatch.setattr(live, "assemble_live_motion", lambda *_: (motion, 7, True))
    result = live.live_translate(request(), Session())
    assert result["sequence"] == 2 and result["tailClipId"] == 7
    assert result["translationStatus"] == "preview" and result["motion"] is motion
    assert result["cacheHit"] is True


def test_incomplete_interpretation_never_builds_partial_motion(monkeypatch):
    monkeypatch.setattr(live, "library_version", lambda _session: "current")
    monkeypatch.setattr(live, "interpret_live", lambda *_: Interpretation(
        "missing-signs", 4, items=[PlaylistItem("HELLO", 7, 500)], unmapped=["X"],
    ))
    monkeypatch.setattr(live, "assemble_live_motion",
                        lambda *_: (_ for _ in ()).throw(AssertionError("must not compose")))
    result = live.live_translate(request(), Session())
    assert result["motion"] is None and result["tailClipId"] is None
