from types import SimpleNamespace

from app.api.v1 import translate as endpoint
from app.services.compose_service import ComposeError


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self, _statement):
        return _Rows(self._rows)


def _item():
    return SimpleNamespace(
        gloss="HELLO", clip_id=1, duration_ms=500, transition_ms=120,
        fingerspelled=False, source_word="hello",
    )


def test_translate_exposes_additive_blend_quality(monkeypatch):
    clip = SimpleNamespace(id=1)
    quality = {"status": "neutral-fallback", "score": 82.0, "algorithmVersion": 2, "seams": []}
    composition = SimpleNamespace(
        blend_quality=quality,
        to_payload=lambda: {"fps": 60, "frameCount": 60, "blendQuality": quality},
    )
    monkeypatch.setattr(endpoint, "build_playlist", lambda _session, _text: ([_item()], []))
    monkeypatch.setattr(endpoint, "compose_clips", lambda _clips: (composition, ["capture warning"]))

    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session([clip]))
    assert result["track"] is not None
    assert result["blendQuality"] == quality
    assert result["warnings"] == ["capture warning"]


def test_translate_returns_no_track_when_quality_gate_rejects(monkeypatch):
    clip = SimpleNamespace(id=1)
    monkeypatch.setattr(endpoint, "build_playlist", lambda _session, _text: ([_item()], []))

    def reject(_clips):
        raise ComposeError("unsafe transition")

    monkeypatch.setattr(endpoint, "compose_clips", reject)
    result = endpoint.translate(endpoint.TranslateRequest(text="hello"), _Session([clip]))
    assert result["track"] is None
    assert result["blendQuality"]["status"] == "rejected"
    assert result["error"] == "unsafe transition"
