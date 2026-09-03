"""English -> gloss sequence.

The load-bearing behaviour is longest-phrase matching: "good morning" is one sign, not GOOD followed
by MORNING, and a word-at-a-time lookup silently misses every multi-word gloss in the vocabulary.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models import Gloss, SignClip
from app.services.translate_service import build_playlist, gloss_variants, normalise


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def add(session, name, duration=2.0):
    gloss = Gloss(name=name, english=name.lower())
    session.add(gloss)
    session.flush()
    session.add(SignClip(
        gloss_id=gloss.id, rig_digest="d" * 16, take=1, is_canonical=True,
        source_csv="x.csv", clip_path="x.signclip", content_hash=name.lower(),
        fps=60.0, frame_count=int(duration * 60), duration=duration, byte_size=1000, qc={},
    ))
    session.flush()


def glosses(items):
    return [i.gloss for i in items]


def test_drops_words_signed_languages_omit():
    assert normalise("the father is here") == ["father", "here"]


def test_gloss_variants_cover_the_usual_spellings():
    assert gloss_variants(["thank", "you"]) == ["THANK_YOU", "THANKYOU"]
    assert "MORNING" in gloss_variants(["mornings"])


def test_single_word_lookup(session):
    add(session, "HELLO")
    items, unmapped = build_playlist(session, "hello")
    assert glosses(items) == ["HELLO"]
    assert unmapped == []


def test_multi_word_gloss_matches_as_one_sign(session):
    add(session, "GOOD_MORNING")
    items, unmapped = build_playlist(session, "good morning")
    assert glosses(items) == ["GOOD_MORNING"]
    assert unmapped == []


def test_concatenated_gloss_spelling_matches(session):
    add(session, "THANKYOU")
    items, unmapped = build_playlist(session, "thank you")
    assert glosses(items) == ["THANKYOU"]
    assert unmapped == []


def test_longest_phrase_wins_over_its_parts(session):
    add(session, "GOOD")
    add(session, "MORNING")
    add(session, "GOOD_MORNING")
    items, _ = build_playlist(session, "good morning")
    assert glosses(items) == ["GOOD_MORNING"]


def test_falls_back_to_the_parts_when_the_phrase_is_not_recorded(session):
    add(session, "GOOD")
    add(session, "MORNING")
    items, _ = build_playlist(session, "good morning")
    assert glosses(items) == ["GOOD", "MORNING"]


def test_phrase_and_word_in_one_sentence(session):
    add(session, "THANKYOU")
    add(session, "FATHER")
    items, unmapped = build_playlist(session, "thank you father")
    assert glosses(items) == ["THANKYOU", "FATHER"]
    assert unmapped == []


def test_unknown_word_is_reported_not_silently_dropped(session):
    add(session, "HELLO")
    items, unmapped = build_playlist(session, "hello xyzzy")
    assert glosses(items) == ["HELLO"]
    assert unmapped == ["xyzzy"]


def test_unknown_word_is_fingerspelled_when_the_alphabet_exists(session):
    add(session, "HELLO")
    for letter in "CAT":
        add(session, letter, duration=0.4)
    items, unmapped = build_playlist(session, "hello cat")
    assert glosses(items) == ["HELLO", "C", "A", "T"]
    assert all(i.fingerspelled for i in items[1:])
    assert unmapped == []


def test_time_markers_lead_the_sentence(session):
    add(session, "TOMORROW")
    add(session, "FATHER")
    items, _ = build_playlist(session, "father tomorrow")
    assert glosses(items) == ["TOMORROW", "FATHER"]


def test_lemmatised_lookup(session):
    add(session, "BOOK")
    items, unmapped = build_playlist(session, "books")
    assert glosses(items) == ["BOOK"]
    assert unmapped == []


def test_greeting_words_are_not_treated_as_time_markers(session):
    """'good morning' must keep its order even when the phrase itself is not recorded."""
    add(session, "GOOD")
    add(session, "MORNING")
    items, _ = build_playlist(session, "good morning")
    assert glosses(items) == ["GOOD", "MORNING"]
