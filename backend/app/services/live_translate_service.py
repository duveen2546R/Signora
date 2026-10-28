"""Incremental English-to-gloss planning for microphone phrases."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Gloss, SignClip
from app.services.function_words import (
    letter_gloss, match_phrases, may_fingerspell, phrase_key, plan_function_words,
)
from app.services.translate_service import (
    Interpretation,
    PlaylistItem,
    Registry,
    interpret,
    load_registry,
    normalise,
)


def _aliases(registry: Registry, recordings: dict[str, SignClip]) -> list[tuple[tuple[str, ...], list[str]]]:
    values: dict[tuple[str, ...], list[str]] = {}
    for pattern in registry.patterns:
        if pattern.fingerspellSlots or len(pattern.glosses) != 1:
            continue
        gloss = pattern.glosses[0]
        if gloss not in recordings:
            continue
        for form in pattern.forms:
            # Same normalisation the input gets, so an omitted article never prevents a match.
            words = phrase_key(form)
            if words and all(re.fullmatch(r"[a-z]+", word) for word in words):
                options = values.setdefault(words, [])
                if gloss not in options:
                    options.append(gloss)
    for gloss, clip in recordings.items():
        if len(gloss) == 1:
            # A letter recording is a fingerspelling unit, not a word: its English name "i" or "a"
            # would otherwise turn the pronoun "I" into the letter I. Letters are reached only
            # through an explicit letter reference or fingerspelling.
            continue
        english = phrase_key(clip.gloss.english or "")
        if english and all(re.fullmatch(r"[a-z]+", word) for word in english):
            options = values.setdefault(english, [])
            if gloss not in options:
                options.append(gloss)
    return sorted(values.items(), key=lambda item: (-len(item[0]), item[0]))


def interpret_live(session: Session, text: str, registry: Registry | None = None,
                   *, literal: bool = False) -> Interpretation:
    """Resolve a finalized speech phrase, then fall back to literal signs/fingerspelling."""
    registry = registry or load_registry()
    exact = interpret(session, text, registry)
    if not literal and exact.status in {"ready", "preview", "missing-signs"}:
        return exact
    if not literal and any(issue.get("code") not in {"unsupported-pattern", "review-required"}
           for issue in exact.issues):
        return exact

    value = normalise(text)
    number_words = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                    "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
                    "hundred", "thousand", "million", "billion"}
    # Function words are decided before any sign is chosen (see `function_words`): an omitted
    # article leaves its neighbours adjacent instead of blocking the phrase for want of letters.
    # Apostrophes are accepted in both modes because contractions are expanded, never spelled.
    plan = plan_function_words(text)
    omitted = [plan.issue()] if plan.issue() else []
    if not value or not re.fullmatch(r"[a-z' ]+", value) or (literal and number_words.intersection(plan.words)):
        return Interpretation("unsupported", registry.version, issues=[{
            "code": "unsupported-speech-token",
            "message": "Live signing currently supports spoken English words, not numbers or symbols.",
        }])
    if not plan.tokens:
        # Nothing to sign is not an error: the stream keeps its tail and the next phrase joins it.
        return Interpretation("function-only", registry.version, pattern_id="literal-live", issues=omitted)

    recordings = session.scalars(
        select(SignClip).join(Gloss).where(SignClip.is_canonical.is_(True))
        .order_by(SignClip.created_at.desc(), SignClip.id.desc())
    ).all()
    by_gloss: dict[str, SignClip] = {}
    for clip in recordings:
        by_gloss.setdefault(clip.gloss.name, clip)
    aliases = _aliases(registry, by_gloss)

    resolved: list[tuple[str, str, bool]] = []
    missing_words: list[str] = []
    missing_letters: list[str] = []
    needs_sign: list[str] = []
    for token, phrase, glosses in match_phrases(plan.tokens, aliases):
        if glosses is not None:
            if len(glosses) != 1:
                return Interpretation("unsupported", registry.version, issues=[{
                    "code": "ambiguous-literal-alias", "message": "Multiple recordings match: " + " ".join(phrase),
                }])
            resolved.extend((gloss, " ".join(phrase), False) for gloss in glosses)
            continue
        if token.kind == "letter":
            if letter_gloss(token) in by_gloss:
                resolved.append((letter_gloss(token), token.source, True))
            else:
                missing_words.append(token.source)
                missing_letters.append(letter_gloss(token))
            continue
        source = token.text
        if not may_fingerspell(token):
            # The pronoun "I" needs its own recorded sign; it is never the letter I.
            needs_sign.append(source)
            continue
        letters = [letter.upper() for letter in source if letter.isalpha()]
        absent = [letter for letter in dict.fromkeys(letters) if letter not in by_gloss]
        if absent:
            missing_words.append(source)
            missing_letters.extend(absent)
        else:
            resolved.extend((letter, source, True) for letter in letters)

    result = Interpretation("preview", registry.version, pattern_id="literal-live", issues=list(omitted))
    if missing_words or needs_sign:
        result.status = "missing-signs"
        result.unmapped = [*missing_words, *needs_sign]
        if missing_words:
            result.issues.append({
                "code": "missing-alphabet",
                "sourceWords": missing_words,
                "glosses": list(dict.fromkeys(missing_letters)),
                "message": "Record canonical alphabet signs for: " + ", ".join(dict.fromkeys(missing_letters)),
            })
        if needs_sign:
            result.issues.append({
                "code": "missing-sign", "sourceWords": needs_sign,
                "message": "Record a sign for: " + ", ".join(dict.fromkeys(needs_sign)),
            })
        return result

    for occurrence, (gloss, source, fingerspelled) in enumerate(resolved):
        clip = by_gloss[gloss]
        result.items.append(PlaylistItem(
            gloss=gloss,
            clip_id=clip.id,
            duration_ms=int(clip.duration * 1000),
            fingerspelled=fingerspelled,
            source_word=source,
            occurrence_index=occurrence,
        ))
    result.issues.append({
        "code": "unreviewed-preview",
        "message": "Playing literal recorded signs and fingerspelling; this is not a reviewed ISL sentence.",
    })
    return result
