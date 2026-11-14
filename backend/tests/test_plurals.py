"""Plural marking: an ordinary plural is BASE + MANY on every literal sequencer.

Checked on YouTube captions, Studio preview and live speech, like the function-word policy, so the
three cannot drift apart. Live speech refuses spoken number words outright, so the "three"/"five"
cases run only where numbers are accepted.
"""
import json

import pytest

from app.services import plurals
from app.services.live_translate_service import interpret_live
from app.services.plurals import PluralRules, resolve_plural, singular_candidates
from app.services.translate_service import interpret_literal_sequence
from app.services.video_plan_service import resolve_caption

from .test_translate import add, session  # noqa: F401 - shared in-memory fixture

SEQUENCERS = {
    "youtube": resolve_caption,
    "studio": interpret_literal_sequence,
    "live": lambda session, text: interpret_live(session, text, literal=True),
}
NUMBERS_ACCEPTED = ["youtube", "studio"]


def glosses(result):
    return [item.gloss for item in result.items]


def plural_labels(result):
    return [issue for issue in result.issues if issue["code"] == "literal-plural-preview"]


@pytest.fixture
def library(session):  # noqa: F811
    for name in ("PEN", "TEACHER", "BOOK", "BOX", "BABY", "MANY", "ALL", "EVERY", "EVERYBODY",
                 "THREE", "FIVE", "LIKE", "IS", "CLASS"):
        add(session, name)
    return session


@pytest.mark.parametrize("name", SEQUENCERS)
@pytest.mark.parametrize("text, expected", [
    ("pen", ["PEN"]),
    ("teacher", ["TEACHER"]),
    ("pens", ["PEN", "MANY"]),
    ("teachers", ["TEACHER", "MANY"]),
    ("all teachers", ["ALL", "TEACHER"]),
    ("many teachers", ["MANY", "TEACHER"]),
    ("every teacher", ["EVERY", "TEACHER"]),
])
def test_plural_marking(library, name, text, expected):
    result = SEQUENCERS[name](library, text)
    assert glosses(result) == expected
    assert "EVERYBODY" not in glosses(result), "EVERYBODY means everyone, never a plural marker"
    assert not any(item.fingerspelled for item in result.items)


@pytest.mark.parametrize("name", NUMBERS_ACCEPTED)
@pytest.mark.parametrize("text, expected", [
    ("three teachers", ["THREE", "TEACHER"]),
    ("five pens", ["FIVE", "PEN"]),
])
def test_a_stated_number_replaces_the_marker(library, name, text, expected):
    assert glosses(SEQUENCERS[name](library, text)) == expected


@pytest.mark.parametrize("name", SEQUENCERS)
def test_many_is_signed_exactly_once(library, name):
    assert glosses(SEQUENCERS[name](library, "many teachers")).count("MANY") == 1


@pytest.mark.parametrize("name", SEQUENCERS)
def test_automatic_base_plus_many_is_labelled_a_literal_plural_preview(library, name):
    result = SEQUENCERS[name](library, "teachers")
    [label] = plural_labels(result)
    assert label["words"] == ["teachers"]
    assert "sourceWords" not in label, "a plural preview is not an unsupported word"
    assert plural_labels(SEQUENCERS[name](library, "all teachers")) == []


@pytest.mark.parametrize("name", SEQUENCERS)
def test_es_and_ies_plurals_use_the_noun_registry(library, name, monkeypatch):
    rules = plurals.load_plural_rules()
    rules.nounBaseGlosses += ["BOX", "BABY"]
    monkeypatch.setattr(plurals, "load_plural_rules", lambda: rules)
    assert glosses(SEQUENCERS[name](library, "boxes")) == ["BOX", "MANY"]
    assert glosses(SEQUENCERS[name](library, "babies")) == ["BABY", "MANY"]


@pytest.mark.parametrize("name", SEQUENCERS)
@pytest.mark.parametrize("word", ["is", "class"])
def test_blocked_words_never_trigger_plural_logic(library, name, word):
    result = SEQUENCERS[name](library, f"{word} pen")
    assert "MANY" not in glosses(result)
    assert plural_labels(result) == []


@pytest.mark.parametrize("name", SEQUENCERS)
def test_a_verb_ending_in_s_is_never_marked_plural(library, name):
    # LIKE is recorded but is not a listed noun base: "likes" must not become LIKE + MANY.
    result = SEQUENCERS[name](library, "teacher likes")
    assert not any(item.gloss in {"LIKE", "MANY"} for item in result.items)
    assert plural_labels(result) == []


@pytest.mark.parametrize("name", SEQUENCERS)
@pytest.mark.parametrize("missing", ["PEN", "MANY"])
def test_missing_base_or_marker_never_gives_a_partial_plural(session, name, missing):  # noqa: F811
    for gloss in {"PEN", "MANY"} - {missing}:
        add(session, gloss)
    result = SEQUENCERS[name](session, "pens")
    assert result.items == [], "neither PEN alone nor MANY alone is signed"
    assert result.status != "literal-preview" or not result.items
    assert "pens" in result.unmapped


@pytest.mark.parametrize("name", SEQUENCERS)
def test_missing_marker_falls_back_to_spelling_the_whole_plural(session, name):  # noqa: F811
    for gloss in ["PEN", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ"]:
        add(session, gloss)
    result = SEQUENCERS[name](session, "pens")
    assert glosses(result) == ["P", "E", "N", "S"], "the plural survives as fingerspelling"
    assert all(item.fingerspelled for item in result.items)


def test_an_exact_plural_sign_is_preferred(session):  # noqa: F811
    for gloss in ("VERBS", "VERB", "MANY"):
        add(session, gloss)
    for sequencer in SEQUENCERS.values():
        assert glosses(sequencer(session, "verbs")) == ["VERBS"]


@pytest.mark.parametrize("word, expected", [
    ("pens", ["pen"]), ("boxes", ["box", "boxe"]), ("babies", ["baby", "babie"]),
    ("is", []), ("class", []), ("news", ["new"]), ("bus", []),
])
def test_singular_candidates(word, expected):
    assert singular_candidates(word) == expected


def test_registry_blocks_the_required_words_and_lists_the_initial_entries():
    rules = plurals.load_plural_rules()
    for word in ("is", "was", "this", "his", "class", "glass", "news", "species"):
        assert word in rules.notPlural
    entries = {e.pluralEnglish: (e.baseGloss, e.pluralMarkerGloss) for e in rules.entries}
    assert entries == {
        "pens": ("PEN", "MANY"), "teachers": ("TEACHER", "MANY"), "dogs": ("DOG", "MANY"),
        "girls": ("GIRL", "MANY"), "books": ("BOOK", "MANY"),
    }
    assert all(e.reviewStatus == "candidate" for e in rules.entries)


def test_everybody_is_rejected_as_a_plural_marker():
    raw = json.loads(plurals.RULES_PATH.read_text())
    raw["entries"][1]["pluralMarkerGloss"] = "EVERYBODY"
    with pytest.raises(ValueError):
        PluralRules.model_validate(raw)


def test_an_approved_entry_is_not_labelled_and_a_rejected_one_is_not_used():
    rules = plurals.load_plural_rules()
    rules.entries[0].reviewStatus = "approved"
    sign = resolve_plural("pens", [], lambda w: None, lambda g: True, rules)
    assert sign.glosses == ("PEN", "MANY") and sign.reviewed
    rules.entries[0].reviewStatus = "rejected"
    assert resolve_plural("pens", [], lambda w: None, lambda g: True, rules) is None
