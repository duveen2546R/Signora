from types import SimpleNamespace
import pytest

from app.services import streaming_library as library
from app.services.compose_service import ComposeError
from tests.test_live_motion import payload


def clip(name, phase=1):
    return SimpleNamespace(content_hash=name, qc={"phases": {"end": phase}})


def test_keys_only_invalidate_participating_clips_and_boundary_states():
    a, b = clip("a"), clip("b")
    key = library.artifact_key({"skeleton": 1}, [a, b], 1.0, "flow")
    assert key == library.artifact_key({"skeleton": 1}, [a, b], 1.0, "flow")
    assert key != library.artifact_key({"skeleton": 1}, [b, a], 1.0, "flow")
    assert key != library.artifact_key({"skeleton": 1}, [a, b], 1.0, "held")
    assert key != library.artifact_key({"skeleton": 1}, [a, b], 0.8, "flow")
    assert key != library.artifact_key({"skeleton": 1}, [a, clip("b", 2)], 1.0, "flow")


def test_artifact_checksum_verification_and_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(library, "directory", lambda: tmp_path)
    key = "b" * 64
    entry = library._save(key, payload(["HELLO"]))
    first = library.read_artifact(key, entry["sha256"])
    assert first is library.read_artifact(key, entry["sha256"])
    library.read_artifact.cache_clear()
    (tmp_path / f"{key}.json.gz").write_bytes(b"corrupted")
    with pytest.raises(ComposeError, match="checksum"):
        library.read_artifact(key, entry["sha256"])


def test_runtime_rejects_missing_variant_without_compiling(monkeypatch):
    monkeypatch.setattr(library, "manifest", lambda: {"libraryVersion": "v", "complete": True, "artifacts": {}})
    monkeypatch.setattr(library, "compose", lambda *_: pytest.fail("runtime cannot compose"))
    with pytest.raises(ComposeError, match="No validated"):
        library.assemble(None, [SimpleNamespace(clip_id=1)], None, "flow", 1.0, "v")


def test_publishing_in_progress_is_not_ready(monkeypatch):
    monkeypatch.setattr(library, "manifest", lambda: {"libraryVersion": "v", "artifacts": {}})
    monkeypatch.setattr(library, "library_version", lambda _: "v")
    assert not library.readiness(None)["published"]


def test_pacing_selects_only_published_rates_and_never_exceeds_recorded_speed(monkeypatch):
    monkeypatch.setattr(library, "manifest", lambda: {})
    def fake_part(_manifest, name):
        return {"frameCount": 60 if name.startswith('1.0:') else 75, "fps": 60}
    monkeypatch.setattr(library, "part", fake_part)
    items = [SimpleNamespace(clip_id=1)]
    assert library.select_rate(items, 500) == 1.0
    assert library.select_rate(items, 2000) == 0.8


def test_motion_response_cache_is_content_addressed_and_byte_bounded(monkeypatch):
    from app.services import live_payload_cache as cache
    monkeypatch.setattr(cache, "MAX_BYTES", 50)
    monkeypatch.setattr(cache, "_bytes", 0)
    from collections import OrderedDict
    monkeypatch.setattr(cache, "_entries", OrderedDict())
    first = cache.put({"value": "a" * 20})
    assert cache.put({"value": "a" * 20}) == first
    cache.put({"value": "b" * 20})
    assert cache.get(first["key"]) is None
    assert cache._bytes <= 50
