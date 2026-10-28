"""The shared function-word policy: what a sign sequence omits, keeps, and expresses instead."""
import pytest

from app.services.function_words import (
    OMITTABLE,
    PROTECTED,
    Token,
    match_phrases,
    may_fingerspell,
    phrase_key,
    plan_function_words,
)


def words(text):
    return plan_function_words(text).words


# --- Omission --------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Hello, the father.", ["hello", "father"]),
    ("A father.", ["father"]),
    ("An answer.", ["answer"]),
    ("Give me all the water.", ["give", "me", "all", "water"]),
])
def test_articles_are_omitted(text, expected):
    assert words(text) == expected


def test_a_unit_of_only_function_words_signs_nothing():
    plan = plan_function_words("The.")
    assert plan.tokens == [] and plan.omitted == ["The"]


def test_omitted_words_are_reported_in_sentence_order():
    assert plan_function_words("The father is a doctor.").omitted == ["The", "is", "a"]


def test_the_omission_report_never_looks_like_a_missing_word():
    """No sourceWord(s) keys, so no surface lists "the" as unsupported or "not signed"."""
    issue = plan_function_words("Hello, the father.").issue()
    assert issue["code"] == "omitted-function-words" and issue["words"] == ["the"]
    assert "sourceWord" not in issue and "sourceWords" not in issue
    assert plan_function_words("Hello father.").issue() is None


# --- Copulas: only in a simple affirmative present-tense statement ---------------------------

def test_present_copula_is_omitted_in_an_affirmative_statement():
    assert words("I am very happy.") == ["i", "very", "happy"]
    assert words("The father is a doctor.") == ["father", "doctor"]


@pytest.mark.parametrize("text, kept", [
    ("Is the father a doctor?", "is"),          # question
    ("The father is not a doctor.", "is"),      # negation
    ("The water was cold.", "was"),             # tense-bearing
    ("He is.", "is"),                           # too short to drop without ambiguity
])
def test_copula_is_kept_where_it_carries_meaning(text, kept):
    assert kept in words(text)


# --- Contractions and do-support -------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("I don't know.", ["i", "not", "know"]),
    ("She doesn't agree.", ["she", "not", "agree"]),
    ("We can't apply.", ["we", "can", "not", "apply"]),
    ("I won't add.", ["i", "will", "not", "add"]),
    ("It's a good morning.", ["it", "good", "morning"]),
    ("I'm able.", ["i", "able"]),  # = "I am able": affirmative, so the copula goes, "I" stays
])
def test_contractions_expand_and_a_hidden_negation_is_never_lost(text, expected):
    assert words(text) == expected


def test_dummy_do_is_omitted_but_past_tense_did_is_kept():
    assert words("Do you want the water") == ["you", "want", "water"]
    assert words("I did not agree.") == ["i", "did", "not", "agree"]
    assert words("I do my work.") == ["i", "do", "my", "work"]  # main-verb "do" is meaningful


def test_a_question_is_recognised_without_a_question_mark():
    """Speech recognisers emit no punctuation."""
    assert plan_function_words("is it good").question is True
    assert words("is it good") == ["is", "it", "good"]


# --- Meaning an omitted word sometimes carries -----------------------------------------------

def test_a_before_a_number_word_is_a_quantity():
    assert words("A hundred people.") == ["one", "hundred", "people"]
    assert words("A dozen.") == ["one", "dozen"]


@pytest.mark.parametrize("text", ["I got an A.", "Plan A is good.", "Grade A.", "The letter a."])
def test_a_named_letter_is_signed_as_that_letter(text):
    letters = [token for token in plan_function_words(text).tokens if token.kind == "letter"]
    assert [token.text for token in letters] == ["a"]


def test_the_pronoun_i_is_never_a_letter():
    tokens = plan_function_words("I am able.").tokens
    assert tokens[0] == Token("i", "word", "I")
    assert may_fingerspell(tokens[0]) is False


# --- Protected words are never omitted -------------------------------------------------------

def test_nothing_omittable_is_also_protected():
    assert not OMITTABLE & PROTECTED


@pytest.mark.parametrize("word", sorted(PROTECTED))
def test_every_protected_word_survives(word):
    # Surrounded by droppable words, in a statement long enough for the copula rule to run. A
    # protected contraction ("cannot") survives as its meaning ("can", "not").
    kept = words(f"The {word} is the father.")
    assert all(part in kept for part in phrase_key(word)), kept


# --- Matching helpers ------------------------------------------------------------------------

def test_phrase_keys_get_the_same_context_free_normalisation():
    assert phrase_key("Good morning") == ("good", "morning")
    assert phrase_key("the end") == ("end",)
    assert phrase_key("don't") == ("do", "not")


def test_longest_phrase_wins_and_never_crosses_a_letter_reference():
    tokens = plan_function_words("good morning father").tokens
    phrases = [(("good", "morning"), "GM"), (("good",), "GOOD"), (("father",), "FATHER")]
    assert [value for _, _, value in match_phrases(tokens, phrases)] == ["GM", "FATHER"]

    tokens = [Token("plan"), Token("a", "letter", "A")]
    steps = list(match_phrases(tokens, [(("plan", "a"), "X")]))
    assert [value for _, _, value in steps] == [None, None]


def test_an_omitted_article_never_splits_a_phrase():
    tokens = plan_function_words("Good the morning.").tokens
    assert [v for _, _, v in match_phrases(tokens, [(("good", "morning"), "GM")])] == ["GM"]
