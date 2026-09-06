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
    monkeypatch.setattr(endpoint, "compose_clips", lambda _: (composition, ["capture warning"]))
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["track"] is not None and result["totalMs"] == 1000
    assert result["translationStatus"] == "ready" and result["language"] == "ISL"
    assert result["patternVersion"] == 2 and result["items"][0]["occurrenceIndex"] == 0


def test_candidate_preview_is_composed_but_not_claimed_as_ready(monkeypatch):
    quality = {"status": "direct", "score": 82.0, "algorithmVersion": 7, "seams": []}
    composition = SimpleNamespace(blend_quality=quality,
                                  to_payload=lambda: {"fps": 60, "frameCount": 60, "blendQuality": quality})
    monkeypatch.setattr(endpoint, "interpret", lambda *_: resolved("preview"))
    monkeypatch.setattr(endpoint, "compose_clips", lambda _: (composition, []))
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["translationStatus"] == "preview"
    assert result["track"] is not None


def test_rejection_preserves_seam_diagnostics(monkeypatch):
    quality = {"status": "rejected", "seams": [{"fromGloss": "HELLO", "toGloss": "FATHER", "reasons": ["too fast"]}]}
    monkeypatch.setattr(endpoint, "interpret", lambda *_: resolved())
    def reject(_): raise ComposeError("unsafe transition", quality)
    monkeypatch.setattr(endpoint, "compose_clips", reject)
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["track"] is None and result["totalMs"] == 0
    assert result["blendQuality"] == quality
    assert result["issues"][0]["code"] == "motion-rejected"


@pytest.mark.parametrize("status", ["unsupported", "missing-signs"])
def test_incomplete_interpretation_never_composes_partial_items(monkeypatch, status):
    monkeypatch.setattr(endpoint, "interpret", lambda *_: resolved(status))
    def forbidden(_): raise AssertionError("must not compose incomplete interpretation")
    monkeypatch.setattr(endpoint, "compose_clips", forbidden)
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session())
    assert result["track"] is None and result["totalMs"] == 0
