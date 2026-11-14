"""Playlist vocabulary import: deterministic take choice, and what captions resolve to afterwards."""
import importlib.util
import json
import string
from pathlib import Path

import pytest

from app.services.video_plan_service import resolve_caption

from .test_video_plan_policy import add, session  # noqa: F401 - shared in-memory fixture

TOOL = Path(__file__).resolve().parents[1] / "tools" / "import_playlist_vocabulary.py"
spec = importlib.util.spec_from_file_location("import_playlist_vocabulary", TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.mark.parametrize("candidates, expected", [
    (["Teacher_1_mixamo.fbx", "Teacher_mixamo.fbx"], "Teacher_mixamo.fbx"),
    (["After_mixamo (1).fbx", "After_mixamo (2).fbx", "After_mixamo.fbx"], "After_mixamo.fbx"),
    (["_Word_2_mixamo.fbx", "Word_1_mixamo.fbx", "Word_mixamo.fbx"], "Word_mixamo.fbx"),
    (["I_3_mixamo.fbx", "I_mixamo (1).fbx", "i_mixamo.fbx"], "i_mixamo.fbx"),
    (["hi_mixamo.fbx", "hi__mixamo.fbx"], "hi__mixamo.fbx"),          # both plain: first sorted
    (["Doctor_2_mixamo.fbx", "Doctor_1_mixamo.fbx"], "Doctor_1_mixamo.fbx"),  # all numbered
])
def test_duplicate_take_selection_is_deterministic(candidates, expected):
    entry = {"status": "choose-canonical-take", "selectedSource": None, "sourceCandidates": candidates}
    assert tool.select_source(entry) == expected
    reordered = {**entry, "sourceCandidates": list(reversed(candidates))}
    assert tool.select_source(reordered) == expected


def test_selected_source_wins_and_missing_source_imports_nothing():
    assert tool.select_source({"status": "ready-for-import-review", "selectedSource": "Go_mixamo.fbx",
                               "sourceCandidates": ["Go_mixamo.fbx"]}) == "Go_mixamo.fbx"
    assert tool.select_source({"status": "missing-source", "selectedSource": None,
                               "sourceCandidates": []}) is None


def test_import_name_round_trips_to_the_manifest_gloss():
    from app.services.ingest_service import gloss_and_take_from_filename
    for gloss in ("GO", "THEY_RE", "S", "SHE_S"):
        assert gloss_and_take_from_filename(Path(tool.import_name(gloss)).stem) == (gloss, 1)


def test_plan_covers_the_whole_alphabet_from_the_real_manifest():
    manifest = json.loads(tool.MANIFEST_PATH.read_text(encoding="utf-8"))
    files = sorted(p.name for p in tool.TRAINER_DIR.iterdir()) if tool.TRAINER_DIR.is_dir() else []
    if not files:
        pytest.skip("trainer/ recordings are not present in this checkout")
    plan = {row["gloss"]: row for row in tool.build_plan(manifest, files)}
    for letter in string.ascii_uppercase:
        assert plan[letter]["source"], f"no trainer/ source for letter {letter}"


def test_letters_never_become_word_patterns():
    records = [
        {"gloss": "I", "clipId": 1, "captionWords": ["I"]},
        {"gloss": "GO", "clipId": 2, "captionWords": ["Go"]},
        {"gloss": "ALL", "clipId": 3, "captionWords": ["All"]},
        {"gloss": "SEE", "clipId": None, "captionWords": ["See"]},
    ]
    registry = {"patterns": [{"id": "all", "forms": ["all"], "glosses": ["ALL"]}]}
    assert tool.candidate_patterns(records, registry) == [
        {"id": "go", "forms": ["go"], "glosses": ["GO"], "reviewStatus": "candidate"},
    ]


def test_an_imported_word_resolves_to_its_direct_sign(session):  # noqa: F811
    add(session, "TEACHER", "teacher")
    for letter in string.ascii_uppercase:
        add(session, letter)
    result = resolve_caption(session, "Teacher")
    assert [item.gloss for item in result.items] == ["TEACHER"]
    assert not any(item.fingerspelled for item in result.items), "a direct sign is never spelled"
    assert result.status == "literal-preview"


def test_an_unknown_word_is_fingerspelled_completely(session):  # noqa: F811
    add(session, "TEACHER", "teacher")
    for letter in string.ascii_uppercase:
        add(session, letter)
    result = resolve_caption(session, "teacher quiz")
    assert [item.gloss for item in result.items] == ["TEACHER", "Q", "U", "I", "Z"]
    assert [item.fingerspelled for item in result.items] == [False, True, True, True, True]
    assert {item.source_word for item in result.items if item.fingerspelled} == {"quiz"}


def test_one_missing_letter_rejects_the_whole_unit(session):  # noqa: F811
    add(session, "TEACHER", "teacher")
    for letter in string.ascii_uppercase.replace("Z", ""):
        add(session, letter)
    result = resolve_caption(session, "teacher quiz")
    assert result.status == "unsupported"
    assert result.items == [], "nothing is partially signed - not even the direct sign"
    assert result.unmapped == ["quiz"]
