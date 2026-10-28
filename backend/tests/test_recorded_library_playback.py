"""Every reviewed recording in the local Signora library must play - through the real API.

Regression for the YouTube test video https://www.youtube.com/watch?v=oK6LGQY_7A4, where 15 of 33
caption units were reported "motion rejected" although every word had a reviewed recording. Root
causes are covered deterministically in test_playback_fallback.py; this module checks the outcome
against the actual library and is skipped wherever that library is not present (CI, fresh clones).

The full 33-unit video plan takes several minutes to compose from cold, so it only runs with
SIGNORA_SLOW_TESTS=1.
"""
import json
import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.ingest.blend import SETTLE_WAIVABLE_REASONS
from app.main import app
from app.models import Gloss, SignClip, VideoPlan
from app.services.compose_service import PLAYABLE_STATUSES, landmark_path

# Canonical glosses the extension showed as "motion rejected" before the fix.
PREVIOUSLY_REJECTED = (
    "ADD", "ADJECTIVE", "ADVISE", "ALWAYS", "APPLY", "APPOINTMENT",
    "ASSUME", "AWAY", "B", "E", "N", "THANKYOU",
)
UNITS_FIXTURE = Path(__file__).parent / "fixtures" / "oK6LGQY_7A4_units.json"


def _library() -> dict[str, SignClip]:
    with SessionLocal() as session:
        clips = session.scalars(
            select(SignClip).join(Gloss).where(SignClip.is_canonical.is_(True))
        ).all()
        found = {}
        for clip in clips:
            reviewed = (clip.qc or {}).get("phases", {}).get("reviewed")
            if reviewed and landmark_path(clip).exists():
                found[clip.gloss.name] = clip.id
        return found


try:
    LIBRARY = _library()
except Exception:  # no database at all
    LIBRARY = {}

pytestmark = pytest.mark.skipif(
    not set(PREVIOUSLY_REJECTED) <= set(LIBRARY),
    reason="the reviewed local recording library is not present",
)


@pytest.fixture(scope="module")
def client():
    logging.disable(logging.WARNING)
    yield TestClient(app)
    logging.disable(logging.NOTSET)


def assert_playable(blend_quality: dict, label: str) -> None:
    assert blend_quality["status"] in PLAYABLE_STATUSES, f"{label}: {blend_quality['status']}"
    for seam in blend_quality["seams"]:
        assert seam["mode"] != "rejected", f"{label}: rejected seam {seam}"
        waived = set(seam.get("waivedChecks", []))
        assert waived <= SETTLE_WAIVABLE_REASONS, f"{label}: waived a mandatory check {waived}"
        if seam["mode"] == "direct":
            assert seam["passed"] is True, f"{label}: direct seam did not pass"


@pytest.mark.parametrize("gloss", PREVIOUSLY_REJECTED)
def test_previously_rejected_sign_plays_directly(client, gloss):
    response = client.get(f"/api/v1/signs/{LIBRARY[gloss]}/track")
    assert response.status_code == 200, response.text
    track = response.json()
    assert track["frameCount"] > 0
    assert any(s["kind"] == "sign" and s["gloss"] == gloss for s in track["segments"])
    assert_playable(track["blendQuality"], gloss)


def test_every_reviewed_recording_plays_directly(client):
    failures = {}
    for gloss, clip_id in sorted(LIBRARY.items()):
        response = client.get(f"/api/v1/signs/{clip_id}/track")
        if response.status_code != 200:
            failures[gloss] = response.json().get("detail")
            continue
        assert_playable(response.json()["blendQuality"], gloss)
    assert not failures, failures


def test_reference_t_pose_no_longer_needs_any_fallback(client):
    """Seven of the twelve failed only because of the T-pose frame: they are now fully direct.

    ADD, AWAY and E also kept that frame but additionally end in motion; THANKYOU and ADVISE never
    kept it. Those five use a labelled settle - see test_previously_rejected_sign_plays_directly.
    """
    tpose_only = ("ADJECTIVE", "ALWAYS", "APPLY", "APPOINTMENT", "ASSUME", "B", "N")
    for gloss in tpose_only:
        track = client.get(f"/api/v1/signs/{LIBRARY[gloss]}/track").json()
        assert track["blendQuality"]["status"] == "direct", gloss


@pytest.mark.parametrize("caption, glosses, spelled", [
    ("Advice.", ["ADVISE"], []),                 # registry alias, not a duplicate recording
    ("Advise.", ["ADVISE"], []),
    ("Bend.", ["B", "E", "N", "D"], ["bend"]),   # complete-alphabet fallback only
    ("Good morning, father.", ["GOOD_MORNING", "FATHER"], []),  # phrase before word
    ("Hello. Hello.", ["HELLO", "HELLO"], []),   # repeats stay separate occurrences
])
def test_caption_resolution_is_unchanged(caption, glosses, spelled):
    from app.services.video_plan_service import resolve_caption
    with SessionLocal() as session:
        result = resolve_caption(session, caption)
    assert [item.gloss for item in result.items] == glosses
    assert sorted({item.source_word for item in result.items if item.fingerspelled}) == spelled
    assert [item.occurrence_index for item in result.items] == list(range(len(glosses)))


def test_words_without_any_recording_stay_unsupported():
    from app.services.video_plan_service import resolve_caption
    with SessionLocal() as session:
        result = resolve_caption(session, "Zebra quixotic.")
    assert result.status == "unsupported" and not result.items
    assert set(result.unmapped) == {"zebra", "quixotic"}


def _vtt(units: list[dict]) -> str:
    def stamp(ms: int) -> str:
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}"
    blocks = [f"{i + 1}\n{stamp(u['startMs'])} --> {stamp(u['endMs'])}\n{u['text']}"
              for i, u in enumerate(units)]
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


@pytest.mark.skipif(os.environ.get("SIGNORA_SLOW_TESTS") != "1",
                    reason="composes the whole test video; set SIGNORA_SLOW_TESTS=1")
def test_youtube_test_video_plan_signs_every_unit(client):
    units = json.loads(UNITS_FIXTURE.read_text())
    response = client.post(
        "/api/v1/video-plans",
        data={"youtube_url": "https://www.youtube.com/watch?v=oK6LGQY_7A4"},
        files={"subtitle": ("captions.vtt", _vtt(units).encode(), "text/vtt")},
    )
    assert response.status_code == 202, response.text
    plan_id = response.json()["id"]
    try:
        # TestClient runs the background preparation before returning control.
        plan = client.get(f"/api/v1/video-plans/{plan_id}").json()
        assert plan["status"] == "ready", plan.get("error")
        assert plan["coverage"]["totalUnits"] == len(units) == 33
        assert plan["coverage"]["signedUnits"] == 33
        assert plan["coverage"]["percent"] == 100.0
        for unit in plan["units"]:
            label = f"[{unit['ordinal']}] {unit['text']}"
            assert unit["motionAvailable"], f"{label}: {unit['issues']}"
            assert not any(i["code"] == "motion-rejected" for i in unit["issues"]), label
            motion = client.get(unit["motionUrl"]).json()
            assert_playable(motion["blendQuality"], label)
        # Repeated words stay separate timed occurrences, and BEND is spelled, not invented.
        bend = [u for u in plan["units"] if u["text"] == "Bend."]
        assert len(bend) == 2 and all(u["glosses"] == ["B", "E", "N", "D"] for u in bend)
        assert all(u["fingerspelledWords"] == ["bend"] for u in bend)
        advise = [u for u in plan["units"] if u["text"] == "Advise."]
        assert advise and advise[0]["glosses"] == ["ADVISE"]
    finally:
        with SessionLocal() as session:
            row = session.get(VideoPlan, plan_id)
            paths = [Path(u.motion_path) for u in row.units if u.motion_path] if row else []
        client.delete(f"/api/v1/video-plans/{plan_id}")
        for path in paths:
            path.unlink(missing_ok=True)
