from app.services.translate_service import Pattern, Registry, interpret_literal_sequence
from .test_translate import add


def test_literal_sequence_matches_longest_phrase_then_direct_words(session):
    add(session, "GOOD_MORNING")
    add(session, "FATHER")
    add(session, "HELLO")
    result = interpret_literal_sequence(session, "good morning father hello", Registry(
        version=1,
        patterns=[Pattern(id="good-morning", forms=["good morning"], glosses=["GOOD_MORNING"])],
    ))
    assert result.status == "literal-preview"
    assert [item.gloss for item in result.items] == ["GOOD_MORNING", "FATHER", "HELLO"]


def test_literal_sequence_spells_only_when_every_letter_exists(session):
    for letter in "BEND":
        add(session, letter)
    result = interpret_literal_sequence(session, "bend", Registry(version=1, patterns=[]))
    assert [item.gloss for item in result.items] == ["B", "E", "N", "D"]
    assert all(item.fingerspelled for item in result.items)
    missing = interpret_literal_sequence(session, "name", Registry(version=1, patterns=[]))
    assert missing.status == "unsupported" and missing.unmapped == ["name"]
