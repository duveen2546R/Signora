from types import SimpleNamespace

import pytest

from app.api.v1 import translate as endpoint
from app.services.compose_service import ComposeError
from app.services.translate_service import Interpretation, PlaylistItem


class _Rows:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Session:
    def scalars(self, _):
        return _Rows([SimpleNamespace(id=1, qc={"phases": {"reviewed": True}})])


def resolved(status="ready"):
    return Interpretation(status, 2, "hello", [PlaylistItem("HELLO", 1, 500)])


def test_translate_exposes_metadata(monkeypatch):
    quality = {"status": "direct", "score": 82.0, "algorithmVersion": 6, "seams": []}
    composition = SimpleNamespace(blend_quality=quality,
                                  to_payload=lambda: {"fps": 60, "frameCount": 60, "blendQuality": quality})
    monkeypatch.setattr(endpoint, "interpret", lambda *_: resolved())
    monkeypatch.setattr(endpoint, "compose_clips", lambda _, **__: (composition, ["capture warning"]))
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["track"] is not None and result["totalMs"] == 1000
    assert result["translationStatus"] == "ready" and result["language"] == "ISL"
    assert result["patternVersion"] == 2 and result["items"][0]["occurrenceIndex"] == 0


def test_candidate_preview_is_composed_but_not_claimed_as_ready(monkeypatch):
    quality = {"status": "direct", "score": 82.0, "algorithmVersion": 7, "seams": []}
    composition = SimpleNamespace(blend_quality=quality,
                                  to_payload=lambda: {"fps": 60, "frameCount": 60, "blendQuality": quality})
    monkeypatch.setattr(endpoint, "interpret", lambda *_: resolved("preview"))
    monkeypatch.setattr(endpoint, "compose_clips", lambda _, **__: (composition, []))
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["translationStatus"] == "preview"
    assert result["track"] is not None


def test_rest_pose_fallback_is_requested_and_played(monkeypatch):
    quality = {"status": "neutral-fallback", "score": 70.0, "algorithmVersion": 7,
               "seams": [{"mode": "neutral-fallback", "passed": True}]}
    composition = SimpleNamespace(blend_quality=quality,
                                  to_payload=lambda: {"fps": 60, "frameCount": 60, "blendQuality": quality})
    requested = {}

    def compose(_clips, **kwargs):
        requested.update(kwargs)
        return composition, []

    monkeypatch.setattr(endpoint, "interpret", lambda *_: resolved())
    monkeypatch.setattr(endpoint, "compose_clips", compose)
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    # Both labelled fallbacks are requested; each seam still reports which one it used.
    assert requested == {"allow_neutral_fallback": True, "allow_reviewed_direct": True}
    assert result["track"] is not None and result["error"] is None
    assert result["blendQuality"]["status"] == "neutral-fallback"


def test_reviewed_settle_is_played_but_rejection_is_not(monkeypatch):
    settle = {"status": "reviewed-direct", "score": 80.0, "algorithmVersion": 11, "seams": [
        {"mode": "reviewed-direct", "passed": False,
         "waivedChecks": ["seam jerk exceeds the adjacent-motion envelope"]}]}
    composition = SimpleNamespace(blend_quality=settle,
                                  to_payload=lambda: {"fps": 60, "frameCount": 60, "blendQuality": settle})
    monkeypatch.setattr(endpoint, "interpret", lambda *_: resolved())
    monkeypatch.setattr(endpoint, "compose_clips", lambda _, **__: (composition, []))
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["track"] is not None and result["error"] is None

    rejected = {**settle, "status": "rejected"}
    composition = SimpleNamespace(blend_quality=rejected,
                                  to_payload=lambda: {"fps": 60, "frameCount": 60, "blendQuality": rejected})
    monkeypatch.setattr(endpoint, "compose_clips", lambda _, **__: (composition, []))
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["track"] is None and result["error"]


def test_rejection_preserves_seam_diagnostics(monkeypatch):
    quality = {"status": "rejected", "seams": [{"fromGloss": "HELLO", "toGloss": "FATHER", "reasons": ["too fast"]}]}
    monkeypatch.setattr(endpoint, "interpret", lambda *_: resolved())
    def reject(_, **__): raise ComposeError("unsafe transition", quality)
    monkeypatch.setattr(endpoint, "compose_clips", reject)
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["track"] is None and result["totalMs"] == 0
    assert result["blendQuality"] == quality
    assert result["issues"][0]["code"] == "motion-rejected"


@pytest.mark.parametrize("status", ["unsupported", "missing-signs"])
def test_incomplete_interpretation_never_composes_partial_items(monkeypatch, status):
    monkeypatch.setattr(endpoint, "interpret", lambda *_: resolved(status))
    def forbidden(_, **__): raise AssertionError("must not compose incomplete interpretation")
    monkeypatch.setattr(endpoint, "compose_clips", forbidden)
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["track"] is None and result["totalMs"] == 0
