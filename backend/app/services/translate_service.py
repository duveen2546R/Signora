"""Resolve reviewed ISL meanings to canonical clips; motion composition is independent."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Gloss, SignClip

REGISTRY_PATH = Path(__file__).with_name("isl_patterns.json")


def normalise(text: str) -> str:
    # Preserve apostrophes, numbers, question marks and negation. Punctuation that can
    # change intent is not erased just to make an input match a supported statement.
    text = unicodedata.normalize("NFKC", text).lower().replace("’", "'")
    text = re.sub(r"[,;.!]+", " ", text)
    return " ".join(text.split())


class Pattern(BaseModel):
    id: str
    forms: list[str] = Field(min_length=1)
    glosses: list[str] = Field(min_length=1)
    reviewStatus: str = "candidate"
    reviewedBy: str = ""
    reviewedAt: str = ""
    reviewEvidence: str = ""
    reviewedClipHashes: dict[str, str] = Field(default_factory=dict)
    requiresUnavailableFeatures: bool = False
    # Only these explicitly named slots may expand to recorded alphabet clips.
    fingerspellSlots: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_review(self):
        if self.reviewStatus not in {"candidate", "approved", "rejected"}:
            raise ValueError("invalid pattern review status")
        if self.reviewStatus == "approved" and not all(
            value.strip() for value in (self.reviewedBy, self.reviewedAt, self.reviewEvidence)
        ):
            raise ValueError("approved patterns require reviewer, date and evidence")
        if self.reviewStatus == "approved":
            date.fromisoformat(self.reviewedAt)
            literals = {g for g in self.glosses if not g.startswith("{")}
            if not literals.issubset(self.reviewedClipHashes):
                raise ValueError("approved patterns must pin the reviewed recording hashes")
        slots = set(self.fingerspellSlots)
        if any(not re.fullmatch(r"[a-z]+", slot) for slot in slots):
            raise ValueError("slot names must contain lowercase letters")
        for form in self.forms:
            if set(re.findall(r"\{([a-z]+)\}", form)) != slots:
                raise ValueError("each form must declare exactly the permitted slots")
        if {g[1:-1] for g in self.glosses if g.startswith("{")} != slots:
            raise ValueError("gloss placeholders must match permitted slots")
        return self


class Registry(BaseModel):
    language: str = "ISL"
    version: int = Field(ge=1)
    patterns: list[Pattern]

    @model_validator(mode="after")
    def validate_registry(self):
        if self.language != "ISL":
            raise ValueError("this registry must describe ISL")
        if len({p.id for p in self.patterns}) != len(self.patterns):
            raise ValueError("pattern IDs must be unique")
        return self


def load_registry() -> Registry:
    return Registry.model_validate(json.loads(REGISTRY_PATH.read_text()))


@dataclass
class PlaylistItem:
    gloss: str
    clip_id: int
    duration_ms: int
    transition_ms: int = 0  # Actual durations live on the composed transition segments.
    fingerspelled: bool = False
    source_word: str = ""
    occurrence_index: int = 0


@dataclass
class Interpretation:
    status: str
    version: int
    pattern_id: str | None = None
    items: list[PlaylistItem] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)


def _match(pattern: Pattern, text: str) -> dict | None:
    for form in pattern.forms:
        expression = re.escape(normalise(form))
        for slot in pattern.fingerspellSlots:
            expression = expression.replace(re.escape("{" + slot + "}"), f"(?P<{slot}>[a-z]+)")
        match = re.fullmatch(expression, text)
        if match:
            return match.groupdict()
    return None


def interpret(session: Session, text: str, registry: Registry | None = None) -> Interpretation:
    registry = registry or load_registry()
    normalised = normalise(text)
    matches = [(p, _match(p, normalised)) for p in registry.patterns]
    candidates = [(p, slots) for p, slots in matches if slots is not None]
    approved = [(p, slots) for p, slots in candidates
                if p.reviewStatus == "approved" and not p.requiresUnavailableFeatures]
    # An exact reviewed phrase has precedence over a generic reviewed spelling slot.
    exact = [(p, slots) for p, slots in approved if not p.fingerspellSlots]
    approved = exact or approved
    if len(approved) > 1:
        return Interpretation("unsupported", registry.version, issues=[{
            "code": "ambiguous-pattern",
            "message": "This sentence has more than one reviewed ISL interpretation.",
        }])

    # Candidate patterns are useful for previewing the recorded vocabulary while linguistic
    # review is pending. Keep that state distinct from a reviewed ISL translation, and only
    # preview a single, renderable candidate so an ambiguous phrase never plays arbitrarily.
    preview = [(p, slots) for p, slots in candidates
               if p.reviewStatus == "candidate" and not p.requiresUnavailableFeatures]
    if not approved and len(preview) != 1:
        pending = bool(preview)
        return Interpretation("unsupported", registry.version, issues=[{
            "code": "ambiguous-pattern" if len(preview) > 1 else (
                "review-required" if pending else "unsupported-pattern"
            ),
            "message": "This sentence matches more than one preview pattern." if len(preview) > 1
                       else "This sentence does not have a supported ISL interpretation.",
        }])

    pattern, slots = (approved or preview)[0]
    result = Interpretation("ready" if approved else "preview", registry.version, pattern.id)
    if not approved:
        result.issues.append({
            "code": "unreviewed-preview",
            "message": "Playing a literal recorded-sign preview; this sentence is awaiting ISL review.",
        })
    recordings = session.scalars(
        select(SignClip).join(Gloss).where(SignClip.is_canonical.is_(True))
        .order_by(SignClip.created_at.desc(), SignClip.id.desc())
    ).all()
    by_gloss = {}
    for clip in recordings:
        by_gloss.setdefault(clip.gloss.name, clip)
    for gloss in pattern.glosses:
        spelling = gloss.startswith("{")
        source = slots[gloss[1:-1]] if spelling else normalised
        names = list(source.upper()) if spelling else [gloss]
        missing = [name for name in names if name not in by_gloss]
        if missing:
            result.unmapped.append(source if spelling else gloss)
            result.issues.append({
                "code": "missing-alphabet" if spelling else "missing-sign",
                "sourceWord": source, "glosses": list(dict.fromkeys(missing)),
                "message": "Record canonical signs for: " + ", ".join(dict.fromkeys(missing)),
            })
            continue
        for name in names:
            clip = by_gloss[name]
            if pattern.reviewStatus == "approved" and pattern.reviewedClipHashes.get(name) != clip.content_hash:
                result.issues.append({
                    "code": "recording-review-required", "clipId": clip.id,
                    "message": f"The current {name} recording needs ISL review for this pattern.",
                })
            result.items.append(PlaylistItem(
                gloss=name, clip_id=clip.id, duration_ms=int(clip.duration * 1000),
                fingerspelled=spelling, source_word=source,
                occurrence_index=len(result.items),
            ))
    blocking_issues = [issue for issue in result.issues if issue["code"] != "unreviewed-preview"]
    if blocking_issues:
        result.status = "missing-signs" if result.unmapped else "unsupported"
    return result


def build_playlist(session: Session, text: str) -> tuple[list[PlaylistItem], list[str]]:
    """Compatibility helper; callers deciding playback must use interpret()."""
    result = interpret(session, text)
    return result.items, result.unmapped
