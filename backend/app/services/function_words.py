"""Which English words a sign sequence omits, which it keeps, and how kept meaning is expressed.

ISL has no articles and no present-tense copula, and English do-support ("I don't know") has no
sign of its own. Signing those words one by one - or fingerspelling them, which is what happened to
"the" whenever T and H were not recorded - clutters the sequence and can block a whole phrase. This
module is the single policy all three literal sequencers share (YouTube captions, Studio preview,
live speech), so the same sentence is signed the same way everywhere.

What it does, in order:

1. Expands contractions so their meaning survives: "don't" -> "do not", "I'm" -> "I am",
   "it's" -> "it is". A negation hidden inside a contraction is never lost.
2. Omits only words that carry no separate sign:
   - articles "a", "an", "the";
   - present-tense copulas "am", "is", "are" in an affirmative statement (questions, negations and
     tense-bearing forms such as "was"/"were" are never simplified - the project's existing rule);
   - dummy do-support: "do"/"does" directly before "not", or opening a question. "did" is kept,
     because it carries past tense.
3. Keeps the meaning an omitted word sometimes carries:
   - "a"/"an" before a number word is a quantity: "a hundred" -> "one hundred";
   - "A" as a letter ("grade A", "plan A", "an A") is the letter A, signed as a letter.
4. Never omits a protected word - negations, quantities, pronouns, question words, emphasis words
   and modals - and guarantees at import time that nothing omittable is also protected.

Omission happens before any sign is chosen, so the surrounding signs are adjacent in the sequence
and composition joins them with one direct transition: there is no gap, hold or blank frame where
the omitted word was.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

ARTICLES = frozenset({"a", "an", "the"})
PRESENT_COPULAS = frozenset({"am", "is", "are"})
DO_SUPPORT = frozenset({"do", "does"})

NEGATIONS = frozenset({
    "not", "no", "never", "neither", "nor", "none", "nothing", "nobody", "nowhere", "cannot",
})
QUANTITIES = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "twenty", "thirty", "forty", "fifty", "hundred", "thousand", "million",
    "billion", "dozen", "half", "all", "some", "many", "much", "few", "several", "more", "most",
    "less", "least", "every", "each", "both", "any", "lot", "lots", "enough", "once", "twice",
    "first", "second", "third", "last",
})
PRONOUNS = frozenset({
    "i", "me", "my", "mine", "myself", "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself",
    "we", "us", "our", "ours", "ourselves", "they", "them", "their", "theirs", "themselves",
    "this", "that", "these", "those",
})
QUESTION_WORDS = frozenset({"who", "whom", "whose", "what", "when", "where", "why", "how", "which"})
EMPHASIS = frozenset({
    "very", "really", "so", "too", "extremely", "absolutely", "totally", "truly", "quite",
    "indeed", "such", "even", "only", "just", "definitely", "always",
})
MODALS = frozenset({"can", "could", "will", "would", "shall", "should", "may", "might", "must"})

PROTECTED = NEGATIONS | QUANTITIES | PRONOUNS | QUESTION_WORDS | EMPHASIS | MODALS
OMITTABLE = ARTICLES | PRESENT_COPULAS | DO_SUPPORT
assert not OMITTABLE & PROTECTED, f"omittable words must never be protected: {OMITTABLE & PROTECTED}"

# Number words after which "a"/"an" means "one" and must be signed as a quantity.
_COUNTED = frozenset({"hundred", "thousand", "million", "billion", "dozen"})
# Nouns after which a single letter names a letter, not an article or a pronoun.
_LETTER_CONTEXT = frozenset({
    "letter", "grade", "plan", "vitamin", "option", "type", "class", "block", "section", "team",
    "row", "part", "level", "size", "point", "group", "category",
})
# Bases after which "'s" is "is"; elsewhere it is a possessive and the token is left unchanged.
_IS_BASES = PRONOUNS | QUESTION_WORDS | {"there", "here", "let"}
# What is left of an irregular negative once "n't" is removed: can't -> "ca", won't -> "wo".
_NEGATIVE_BASES = {"ca": "can", "wo": "will", "sha": "shall", "ai": "is"}
_SUFFIXES = {"'m": "am", "'re": "are", "'ve": "have", "'ll": "will", "'d": "would"}

_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")


@dataclass(frozen=True)
class Token:
    """One retained unit of meaning. `kind` is "word" or "letter" (an explicit letter reference)."""

    text: str
    kind: str = "word"
    source: str = ""


@dataclass
class FunctionWordPlan:
    tokens: list[Token] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)
    question: bool = False
    negated: bool = False

    @property
    def words(self) -> list[str]:
        return [token.text for token in self.tokens]

    def issue(self) -> dict | None:
        """Informational, never blocking, and deliberately free of `sourceWord(s)` keys so no
        surface lists an omitted article as an unsupported word."""
        if not self.omitted:
            return None
        return {
            "code": "omitted-function-words", "words": list(self.omitted),
            "message": "Omitted words that have no separate sign: " + ", ".join(self.omitted) + ".",
        }


def _expand(raw: str) -> list[tuple[str, str]]:
    """One raw token -> [(lowercase word, original spelling)], with contractions expanded."""
    word = raw.lower()
    if word == "cannot":
        return [("can", raw), ("not", raw)]
    if word.endswith("n't") and len(word) > 3:
        base = word[:-3]
        return [(_NEGATIVE_BASES.get(base, base), raw), ("not", raw)]
    if word == "let's":
        return [("let", raw), ("us", raw)]
    if word.endswith("'s") and word[:-2] in _IS_BASES:
        return [(word[:-2], raw), ("is", raw)]
    for suffix, full in _SUFFIXES.items():
        if word.endswith(suffix) and len(word) > len(suffix):
            return [(word[:-len(suffix)], raw), (full, raw)]
    return [(word, raw)]


def plan_function_words(text: str) -> FunctionWordPlan:
    """Decide which words of `text` are signed, in order. See the module docstring."""
    value = unicodedata.normalize("NFKC", text).replace("’", "'")
    question = "?" in value
    expanded: list[tuple[str, str]] = []
    for raw in _TOKEN.findall(value):
        expanded.extend(_expand(raw))

    words = [word for word, _ in expanded]
    # Speech recognition never emits "?", so a yes/no question is also recognised by its shape:
    # an auxiliary followed by a pronoun ("do you want", "is it", "can we").
    auxiliary_question = len(words) > 1 and words[1] in PRONOUNS and words[0] in (
        DO_SUPPORT | PRESENT_COPULAS | MODALS | {"did", "was", "were", "have", "has"}
    )
    question = question or bool(QUESTION_WORDS.intersection(words)) or auxiliary_question
    negated = bool(NEGATIONS.intersection(words))
    plan = FunctionWordPlan(question=question, negated=negated)

    def previous(i: int) -> str:
        return words[i - 1] if i > 0 else ""

    dropped: list[tuple[int, str]] = []

    def omit(i: int) -> None:
        # Report what was dropped as written - or, for half of a contraction, the dropped word.
        word, raw = expanded[i]
        dropped.append((i, word if "'" in raw else raw))

    candidates: list[Token | None] = []
    for i, (word, raw) in enumerate(expanded):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        letter_context = previous(i) in _LETTER_CONTEXT or previous(i) in ARTICLES
        if len(word) == 1 and letter_context:
            # "grade A", "an A", "the letter i": a named letter, signed as that letter.
            candidates.append(Token(word, "letter", raw))
        elif word in ("a", "an") and nxt in _COUNTED:
            # "a hundred" is a quantity, not an article: keep its meaning as "one".
            candidates.append(Token("one", "word", raw))
        elif word in ARTICLES:
            omit(i)
            candidates.append(None)
        elif word in DO_SUPPORT and (nxt == "not" or (i == 0 and question)):
            omit(i)
            candidates.append(None)
        else:
            candidates.append(Token(word, "word", raw))

    retained = [(i, token) for i, token in enumerate(candidates) if token is not None]
    # Copulas: the existing caption rule - only a simple affirmative present-tense statement with
    # enough content that dropping the copula cannot leave an ambiguous fragment.
    if not question and not negated and len(retained) >= 3:
        kept = []
        for i, token in retained:
            if token.kind == "word" and token.text in PRESENT_COPULAS:
                omit(i)
            else:
                kept.append((i, token))
        retained = kept
    plan.tokens = [token for _, token in retained]
    plan.omitted = [word for _, word in sorted(dropped)]
    return plan


def phrase_key(form: str) -> tuple[str, ...]:
    """A registry form or English name as matchable words: contractions expanded, articles dropped.

    Only the context-free part of the policy is applied - a phrase is matched inside sentences of
    any shape, so the sentence-level copula and do-support rules cannot be decided here.
    """
    value = unicodedata.normalize("NFKC", form).replace("’", "'")
    words = [word for raw in _TOKEN.findall(value) for word, _ in _expand(raw)]
    return tuple(word for word in words if word not in ARTICLES)


def match_phrases(tokens, phrases, accept=lambda value: value is not None):
    """Longest phrase first over retained tokens: yields (token, phrase, value) per step.

    `phrases` is [(word tuple, value)]; a phrase is matched only over consecutive *word* tokens
    (never across a letter reference) and only when `accept(value)`. Unmatched tokens yield
    (token, None, None) for the caller's own per-word handling. Because omitted function words are
    already gone, "good the morning" can still match "good morning" - and an omitted article never
    splits a phrase or leaves a gap between two signs.
    """
    ordered = sorted(phrases, key=lambda entry: len(entry[0]), reverse=True)
    at = 0
    while at < len(tokens):
        run = []
        for token in tokens[at:]:
            if token.kind != "word":
                break
            run.append(token.text)
        match = next((
            (phrase, value) for phrase, value in ordered
            if phrase and tuple(run[:len(phrase)]) == tuple(phrase) and accept(value)
        ), None)
        if match is not None:
            phrase, value = match
            yield tokens[at], tuple(phrase), value
            at += len(phrase)
        else:
            yield tokens[at], None, None
            at += 1


def may_fingerspell(token: Token) -> bool:
    """A one-letter *word* is the pronoun "I", never the letter I; only a letter reference or a word
    of two or more letters may fall back to fingerspelling."""
    return token.kind == "letter" or len(token.text) > 1


def letter_gloss(token: Token) -> str:
    return token.text.upper()
