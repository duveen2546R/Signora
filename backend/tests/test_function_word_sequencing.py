"""All three text-to-sign sequencers apply the same function-word policy.

YouTube captions (`resolve_caption`), Studio preview (`interpret_literal_sequence`) and live speech
(`interpret_live`) used to disagree: captions dropped articles, Studio reported "the" as a missing
word, and live speech blocked the whole phrase because T and H were not recorded. Every behaviour
below is checked on all three so they cannot drift apart again.
"""
import pytest

from app.services.live_translate_service import interpret_live
from app.services.translate_service import interpret_literal_sequence
from app.services.video_plan_service import resolve_caption

from .test_translate import add

SEQUENCERS = {
    "youtube": resolve_caption,
    "studio": interpret_literal_sequence,
    "live": lambda session, text: interpret_live(session, text, literal=True),
}
PLAYABLE = {"literal-preview", "preview", "ready"}


def glosses(result):
    return [item.gloss for item in result.items]


@pytest.fixture
def library(session):
    for name in ("HELLO", "FATHER", "GOOD_MORNING", "ABLE", "CAN", "NOT", "A", "I", "T", "H", "E"):
        add(session, name)
    return session


@pytest.mark.parametrize("name", SEQUENCERS)
def test_an_article_is_omitted_and_its_neighbours_are_signed_back_to_back(library, name):
    result = SEQUENCERS[name](library, "Hello, the father.")
    assert result.status in PLAYABLE
    assert glosses(result) == ["HELLO", "FATHER"]
    # Contiguous occurrences: nothing is reserved for the omitted word, so composition joins
    # HELLO directly to FATHER with no gap.
    assert [item.occurrence_index for item in result.items] == [0, 1]
    omitted = [issue for issue in result.issues if issue["code"] == "omitted-function-words"]
    assert omitted and omitted[0]["words"] == ["the"]


@pytest.mark.parametrize("name", SEQUENCERS)
def test_an_omitted_article_is_never_fingerspelled_even_when_its_letters_exist(library, name):
    """T, H and E are all recorded here - "the" must still not be spelled."""
    result = SEQUENCERS[name](library, "The father.")
    assert glosses(result) == ["FATHER"]


@pytest.mark.parametrize("name", SEQUENCERS)
def test_the_article_a_is_never_signed_as_the_letter_a(library, name):
    assert glosses(SEQUENCERS[name](library, "A father.")) == ["FATHER"]


@pytest.mark.parametrize("name", SEQUENCERS)
def test_a_named_letter_is_signed_as_that_letter(library, name):
    result = SEQUENCERS[name](library, "Hello, an A.")
    assert glosses(result) == ["HELLO", "A"]
    assert result.items[1].fingerspelled is True


@pytest.mark.parametrize("name", SEQUENCERS)
def test_the_pronoun_i_is_never_signed_as_the_letter_i(library, name):
    """Pronouns are preserved; with no pronoun sign recorded the word is reported, not spelled."""
    result = SEQUENCERS[name](library, "I am able.")
    assert "I" not in glosses(result)
    assert "i" in result.unmapped


@pytest.mark.parametrize("name", SEQUENCERS)
def test_a_negation_inside_a_contraction_is_signed(library, name):
    result = SEQUENCERS[name](library, "Father can't.")
    assert result.status in PLAYABLE
    assert glosses(result) == ["FATHER", "CAN", "NOT"]


@pytest.mark.parametrize("name", SEQUENCERS)
def test_only_function_words_is_not_an_error(library, name):
    """Nothing to sign: no motion, no blank animation, and - for live speech - no broken stream."""
    result = SEQUENCERS[name](library, "The.")
    assert result.status == "function-only"
    assert result.items == [] and result.unmapped == []


@pytest.mark.parametrize("name", SEQUENCERS)
def test_a_phrase_still_matches_across_an_omitted_article(library, name):
    result = SEQUENCERS[name](library, "Good morning, the father.")
    assert glosses(result) == ["GOOD_MORNING", "FATHER"]


def test_live_speech_no_longer_blocks_a_phrase_on_an_article(session):
    """The regression that mattered most: without T and H, "the" used to block everything."""
    for name in ("HELLO", "FATHER"):
        add(session, name)
    result = interpret_live(session, "hello the father", literal=True)
    assert result.status == "preview"
    assert glosses(result) == ["HELLO", "FATHER"]
