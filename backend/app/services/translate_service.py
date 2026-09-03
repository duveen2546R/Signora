"""English text -> a sequence of signs the avatar can perform.

Deliberately rule-based to start with: deterministic, inspectable, and it fails in ways you can see
and fix by adding a gloss. Sign languages are not word-for-word English, so this does three things:
normalise the words, look each one up, and fingerspell whatever is left over.

The reordering here is minimal on purpose. Real grammar (topic-comment ordering, time markers first,
non-manual markers) depends on which sign language the vocabulary is being recorded in - see the open
question in the plan - so it is kept in one small, swappable function.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Gloss, SignClip

# Words English needs but signed languages generally drop.
_DROP = {
    "a", "an", "the", "is", "am", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "of", "to", "will", "would", "shall",
}
# Fronting a time marker is a robust feature across signed languages, but only for words that are
# unambiguously temporal. "morning", "evening" and "night" are excluded on purpose: they appear far
# more often inside greetings ("good morning") than as time markers, and fronting them there
# reverses the sign order of the greeting.
_TIME_WORDS = {"yesterday", "today", "tomorrow", "now", "later", "before", "after"}

_SUFFIXES = (("ies", "y"), ("es", ""), ("s", ""), ("ing", ""), ("ed", ""))


def lemmatise(word: str) -> str:
    for suffix, replacement in _SUFFIXES:
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)] + replacement
    return word


def normalise(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z']+", text.lower())
    return [w for w in words if w not in _DROP]


# Longest phrase we will try to match as a single sign. "good morning" and "thank you" are single
# signs, not sequences of their parts, and most multi-word glosses are two or three words.
MAX_PHRASE_WORDS = 4


def gloss_variants(words: list[str]) -> list[str]:
    """Candidate gloss names for a run of words, most specific spelling first."""
    joined = "_".join(words).upper()
    variants = [joined]
    if len(words) > 1:
        variants.append("".join(words).upper())   # THANKYOU
    else:
        variants.append(lemmatise(words[0]).upper())
    # De-duplicate, preserving order.
    seen, out = set(), []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def reorder(units: list[list[str]]) -> list[list[str]]:
    """Time markers lead the sentence in most signed languages."""
    lead = [u for u in units if any(w in _TIME_WORDS for w in u)]
    rest = [u for u in units if u not in lead]
    return lead + rest


@dataclass
class PlaylistItem:
    gloss: str
    clip_id: int | None
    duration_ms: int
    transition_ms: int
    fingerspelled: bool = False
    source_word: str = ""


# A transition shorter than this reads as a jump cut; longer than this and the sentence drags.
MIN_TRANSITION_MS = 120
MAX_TRANSITION_MS = 300


def _canonical_clip(session: Session, gloss_name: str) -> SignClip | None:
    stmt = (
        select(SignClip)
        .join(Gloss)
        .where(Gloss.name == gloss_name.upper())
        .order_by(SignClip.is_canonical.desc(), SignClip.created_at.desc())
    )
    return session.scalars(stmt).first()


def build_playlist(session: Session, text: str) -> tuple[list[PlaylistItem], list[str]]:
    """Resolve `text` into clips, matching the longest phrase that has a recorded sign.

    Greedy longest-match matters: "good morning" is one sign, not GOOD followed by MORNING, and
    looking words up one at a time would miss every multi-word gloss in the vocabulary.
    """
    words = normalise(text)

    # First pass: segment the sentence into the longest runs that have a recorded sign.
    units: list[tuple[list[str], SignClip | None]] = []
    i = 0
    while i < len(words):
        for span in range(min(MAX_PHRASE_WORDS, len(words) - i), 0, -1):
            phrase = words[i:i + span]
            clip = next(
                (c for c in (_canonical_clip(session, v) for v in gloss_variants(phrase)) if c),
                None,
            )
            if clip is not None:
                units.append((phrase, clip))
                i += span
                break
        else:
            units.append(([words[i]], None))
            i += 1

    # Second pass: order the resolved units, then expand into playable items.
    ordered = reorder([u for u, _ in units])
    lookup = {tuple(u): c for u, c in units}

    items: list[PlaylistItem] = []
    unmapped: list[str] = []

    for unit in ordered:
        clip = lookup[tuple(unit)]
        word = " ".join(unit)

        if clip is not None:
            items.append(PlaylistItem(
                gloss=clip.gloss.name, clip_id=clip.id,
                duration_ms=int(clip.duration * 1000), transition_ms=MIN_TRANSITION_MS,
                source_word=word,
            ))
            continue

        # Fall back to fingerspelling, which needs the alphabet recorded as its own glosses.
        letters = [_canonical_clip(session, ch) for ch in word.upper() if ch.isalpha()]
        if letters and all(letters):
            for ch, letter_clip in zip(
                [c for c in word.upper() if c.isalpha()], letters, strict=True
            ):
                items.append(PlaylistItem(
                    gloss=ch, clip_id=letter_clip.id,
                    duration_ms=int(letter_clip.duration * 1000),
                    transition_ms=MIN_TRANSITION_MS // 2,
                    fingerspelled=True, source_word=word,
                ))
        else:
            unmapped.append(word)

    return items, unmapped
