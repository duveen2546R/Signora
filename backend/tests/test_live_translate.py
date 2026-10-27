import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models import Gloss, SignClip
from app.services.live_translate_service import interpret_live
from app.services.translate_service import Pattern, Registry


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as value:
        yield value


def add(session, name):
    gloss = Gloss(name=name, english=name.lower().replace("_", " "))
    session.add(gloss)
    session.flush()
    clip = SignClip(
        gloss_id=gloss.id, rig_digest="d" * 16, take=1, is_canonical=True,
        source_csv="x.csv", clip_path="x.signclip", content_hash=name.lower(),
        fps=60, frame_count=120, duration=2, byte_size=1000, qc={},
    )
    session.add(clip)
    session.flush()
    return clip


def candidate(pattern_id, form, gloss):
    return Pattern(id=pattern_id, forms=[form], glosses=[gloss])


def registry(*patterns):
    return Registry(version=3, patterns=list(patterns))


def test_literal_fallback_uses_longest_known_phrase_then_fingerspells(session):
    for name in ("THANKYOU", "A", "D"):
        add(session, name)
    result = interpret_live(
        session, "thank you ada",
        registry(candidate("thanks", "thank you", "THANKYOU")),
    )
    assert result.status == "preview"
    assert [item.gloss for item in result.items] == ["THANKYOU", "A", "D", "A"]
    assert [item.fingerspelled for item in result.items] == [False, True, True, True]


def test_missing_alphabet_blocks_the_entire_phrase(session):
    add(session, "A")
    result = interpret_live(session, "ada", registry())
    assert result.status == "missing-signs"
    assert result.unmapped == ["ada"]
    assert result.issues[0]["glosses"] == ["D"]
    assert result.items == []


@pytest.mark.parametrize("text", ["hello 2", "hello?", "hello # father"])
def test_numbers_and_symbols_are_not_silently_removed(session, text):
    result = interpret_live(session, text, registry())
    assert result.status == "unsupported"
    assert result.issues[0]["code"] == "unsupported-speech-token"


def test_repeated_letters_keep_distinct_occurrences(session):
    for name in ("H", "E", "L", "O"):
        add(session, name)
    result = interpret_live(session, "hello", registry())
    assert [item.gloss for item in result.items] == ["H", "E", "L", "L", "O"]
    assert [item.occurrence_index for item in result.items] == list(range(5))
