"""Explicit plural marking: an ordinary English plural is signed as its singular base + MANY.

"pens" signed as PEN alone would lose the singular/plural distinction the caption made, so a plural
with no stated quantity becomes PEN + MANY, the system's generic plural marker. Shared by the three
literal sequencers (YouTube captions, Studio preview, live speech), like `function_words`.

Order of preference for a plural word:
  a. an exact recorded/registered sign for the plural itself - matched by the caller's phrase
     table before this module is consulted ("verbs", "vowels");
  b. an explicit entry in plural_rules.json ("teachers" -> TEACHER + MANY);
  c. the automatic -s/-es/-ies rule, only onto a base listed in `nounBaseGlosses`, because the same
     endings also mark verbs ("likes", "wants") and those must never gain MANY.

A stated quantity replaces the marker: "three teachers" -> THREE TEACHER, "many teachers" -> MANY
TEACHER (the quantity word is signed by the caller as usual). The base and the marker are emitted
together or not at all; when either is missing the caller continues with its existing alphabet or
unsupported handling, so plural meaning is never silently dropped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from pydantic import BaseModel, Field, model_validator

RULES_PATH = Path(__file__).with_name("plural_rules.json")

# Words before a plural noun that already say how many: no MANY is added after them.
QUANTIFIERS = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion", "dozen", "couple",
    "many", "all", "some", "few", "several", "both", "most", "more", "lot", "lots",
    "every", "each", "no", "any", "enough", "numerous", "various",
})


class PluralEntry(BaseModel):
    pluralEnglish: str
    singularEnglish: str
    baseGloss: str
    pluralMarkerGloss: str = "MANY"
    reviewStatus: str = "candidate"
    notes: str = ""

    @model_validator(mode="after")
    def validate_entry(self):
        if self.reviewStatus not in {"candidate", "approved", "rejected"}:
            raise ValueError("invalid plural entry review status")
        if self.pluralMarkerGloss == "EVERYBODY":
            raise ValueError("EVERYBODY means everyone; it is not a plural marker")
        self.pluralEnglish = self.pluralEnglish.lower()
        self.singularEnglish = self.singularEnglish.lower()
        return self


class PluralRules(BaseModel):
    version: int = Field(ge=1)
    pluralMarkerGloss: str = "MANY"
    notes: str = ""
    entries: list[PluralEntry] = Field(default_factory=list)
    nounBaseGlosses: list[str] = Field(default_factory=list)
    notPlural: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rules(self):
        if self.pluralMarkerGloss == "EVERYBODY":
            raise ValueError("EVERYBODY means everyone; it is not a plural marker")
        plurals = [entry.pluralEnglish for entry in self.entries]
        if len(set(plurals)) != len(plurals):
            raise ValueError("each plural word may have only one entry")
        self.notPlural = [word.lower() for word in self.notPlural]
        if set(plurals) & set(self.notPlural):
            raise ValueError("a word cannot be both an explicit plural and blocked")
        return self


def load_plural_rules() -> PluralRules:
    return PluralRules.model_validate(json.loads(RULES_PATH.read_text()))


@dataclass(frozen=True)
class PluralSign:
    glosses: tuple[str, ...]  # (BASE,) after a stated quantity, otherwise (BASE, MARKER)
    marked: bool              # the plural marker was added
    reviewed: bool            # an interpreter approved the explicit entry


def singular_candidates(word: str) -> list[str]:
    """Possible singulars of a regular plural, most specific first; empty when not plural-shaped."""
    if len(word) < 3 or not word.endswith("s") or word.endswith(("ss", "us", "is")):
        return []
    candidates = []
    if word.endswith("ies") and len(word) > 4:
        candidates.append(word[:-3] + "y")                       # babies -> baby
    if word.endswith("es") and word[:-2].endswith(("s", "x", "z", "ch", "sh", "o")):
        candidates.append(word[:-2])                             # boxes -> box
    candidates.append(word[:-1])                                 # pens -> pen
    return list(dict.fromkeys(candidates))


def is_quantified(previous_words: Iterable[str]) -> bool:
    """Does the retained word before this one state a quantity? ("lots of", "all of" count.)"""
    words = list(previous_words)
    if words and words[-1] == "of":
        words.pop()
    return bool(words) and words[-1] in QUANTIFIERS


def resolve_plural(
    word: str,
    previous_words: Iterable[str],
    lookup: Callable[[str], str | None],
    available: Callable[[str], bool],
    rules: PluralRules | None = None,
) -> PluralSign | None:
    """The plural reading of `word`, or None to let the caller continue as before.

    `lookup(singular)` returns the single gloss a singular English word resolves to; `available`
    says whether a gloss has a usable recording under the caller's current policy.
    """
    rules = rules or load_plural_rules()
    word = word.lower()
    if word in rules.notPlural:
        return None
    entry = next((e for e in rules.entries if e.pluralEnglish == word), None)
    if entry is not None and entry.reviewStatus == "rejected":
        return None
    if entry is not None:
        base, marker, reviewed = entry.baseGloss, entry.pluralMarkerGloss, entry.reviewStatus == "approved"
    else:
        nouns = set(rules.nounBaseGlosses)
        base = next((gloss for gloss in map(lookup, singular_candidates(word)) if gloss in nouns), None)
        if base is None:
            return None
        marker, reviewed = rules.pluralMarkerGloss, False
    quantified = is_quantified(previous_words)
    glosses = (base,) if quantified else (base, marker)
    if not all(available(gloss) for gloss in glosses):
        return None
    return PluralSign(glosses, marked=not quantified, reviewed=reviewed)


def plural_issue(words: list[str]) -> dict | None:
    """Informational label; uses `words`, not `sourceWords`, because nothing here is unsupported."""
    if not words:
        return None
    return {
        "code": "literal-plural-preview", "words": list(dict.fromkeys(words)),
        "message": "Literal plural preview: shown as the singular sign + MANY, not yet "
                   "interpreter-reviewed: " + ", ".join(dict.fromkeys(words)) + ".",
    }
