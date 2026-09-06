"""Incremental English-to-gloss planning for microphone phrases."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Gloss, SignClip
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
            words = tuple(normalise(form).split())
            if words and all(re.fullmatch(r"[a-z]+", word) for word in words):
                values.setdefault(words, [gloss])
    for gloss, clip in recordings.items():
        english = tuple(normalise(clip.gloss.english or "").split())
        if english and all(re.fullmatch(r"[a-z]+", word) for word in english):
            values.setdefault(english, [gloss])
    return sorted(values.items(), key=lambda item: (-len(item[0]), item[0]))


def interpret_live(session: Session, text: str, registry: Registry | None = None) -> Interpretation:
    """Resolve a finalized speech phrase, then fall back to literal signs/fingerspelling."""
    registry = registry or load_registry()
    exact = interpret(session, text, registry)
    if exact.status in {"ready", "preview", "missing-signs"}:
        return exact
    if any(issue.get("code") not in {"unsupported-pattern", "review-required"}
           for issue in exact.issues):
        return exact

    value = normalise(text)
    if not value or not re.fullmatch(r"[a-z' ]+", value):
        return Interpretation("unsupported", registry.version, issues=[{
            "code": "unsupported-speech-token",
            "message": "Live signing currently supports spoken English words, not numbers or symbols.",
        }])

    recordings = session.scalars(
        select(SignClip).join(Gloss).where(SignClip.is_canonical.is_(True))
        .order_by(SignClip.created_at.desc(), SignClip.id.desc())
    ).all()
    by_gloss: dict[str, SignClip] = {}
    for clip in recordings:
        by_gloss.setdefault(clip.gloss.name, clip)
    aliases = _aliases(registry, by_gloss)

    words = value.split()
    resolved: list[tuple[str, str, bool]] = []
    missing_words: list[str] = []
    missing_letters: list[str] = []
    at = 0
    while at < len(words):
        matched = next((entry for entry in aliases
                        if tuple(words[at:at + len(entry[0])]) == entry[0]), None)
        if matched:
            phrase, glosses = matched
            source = " ".join(phrase)
            resolved.extend((gloss, source, False) for gloss in glosses)
            at += len(phrase)
            continue

        source = words[at]
        letters = [letter.upper() for letter in source if letter.isalpha()]
        absent = [letter for letter in dict.fromkeys(letters) if letter not in by_gloss]
        if absent:
            missing_words.append(source)
            missing_letters.extend(absent)
        else:
            resolved.extend((letter, source, True) for letter in letters)
        at += 1

    result = Interpretation("preview", registry.version, pattern_id="literal-live")
    if missing_words:
        result.status = "missing-signs"
        result.unmapped = missing_words
        result.issues.append({
            "code": "missing-alphabet",
            "sourceWords": missing_words,
            "glosses": list(dict.fromkeys(missing_letters)),
            "message": "Record canonical alphabet signs for: " + ", ".join(dict.fromkeys(missing_letters)),
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
