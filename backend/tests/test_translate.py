"""Full-sentence interpretation is possible only through reviewed ISL patterns."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models import Gloss, SignClip
from app.services.translate_service import Registry, Pattern, interpret, normalise, load_registry


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as value:
        yield value


def add(session, name, canonical=True):
    gloss = Gloss(name=name, english=name.lower())
    session.add(gloss)
    session.flush()
    clip = SignClip(gloss_id=gloss.id, rig_digest="d" * 16, take=1, is_canonical=canonical,
                    source_csv="x.csv", clip_path="x.signclip", content_hash=name.lower(),
                    fps=60, frame_count=120, duration=2, byte_size=1000, qc={})
    session.add(clip)
    session.flush()
    return clip


def approved(id="thanks-father", forms=None, glosses=None, **kwargs):
    return Pattern(id=id, forms=forms or ["thank you father"], glosses=glosses or ["THANKYOU", "FATHER"],
                   reviewStatus="approved", reviewedBy="Test fixture reviewer",
                   reviewedAt="2026-09-05", reviewEvidence="Synthetic test approval, never deployed",
                   reviewedClipHashes={g: g.lower() for g in ["HELLO", "THANKYOU", "FATHER", "A", "D"]}, **kwargs)


def registry(*patterns):
    return Registry(version=2, patterns=list(patterns))


def test_production_candidates_are_not_claimed_as_reviewed():
    assert all(p.reviewStatus == "candidate" for p in load_registry().patterns)


def test_normalisation_preserves_meaning():
    assert normalise("  THANK you, Father. ") == "thank you father"
    assert normalise("Father isn't here?") == "father isn't here?"
    assert normalise("123") == "123"


def test_complete_phrase_resolves_to_canonical_recordings(session):
    add(session, "THANKYOU")
    add(session, "FATHER")
    result = interpret(session, "Thank you, FATHER!", registry(approved()))
    assert result.status == "ready"
    assert [i.gloss for i in result.items] == ["THANKYOU", "FATHER"]
    assert result.pattern_id == "thanks-father" and result.version == 2


@pytest.mark.parametrize("text", ["thank you father tomorrow", "do not thank you father", "thank you father?", "father is here"])
def test_known_words_do_not_enable_unsupported_grammar(session, text):
    add(session, "THANKYOU")
    add(session, "FATHER")
    result = interpret(session, text, registry(approved()))
    assert result.status == "unsupported" and not result.items


def test_unapproved_and_unrenderable_patterns_are_blocked(session):
    for pattern in [Pattern(id="hello", forms=["hello"], glosses=["HELLO"]),
                    approved(forms=["hello"], glosses=["HELLO"], requiresUnavailableFeatures=True)]:
        assert interpret(session, "hello", registry(pattern)).status == "unsupported"


def test_approval_requires_evidence():
    with pytest.raises(ValueError, match="reviewer, date and evidence"):
        Pattern(id="hello", forms=["hello"], glosses=["HELLO"], reviewStatus="approved")


def test_missing_canonical_is_reported_without_using_another_take(session):
    add(session, "THANKYOU", canonical=False)
    add(session, "FATHER")
    result = interpret(session, "thank you father", registry(approved()))
    assert result.status == "missing-signs" and result.unmapped == ["THANKYOU"]


def test_repeated_signs_have_distinct_occurrences(session):
    add(session, "HELLO")
    result = interpret(session, "hello hello", registry(approved(forms=["hello hello"], glosses=["HELLO", "HELLO"])))
    assert [i.occurrence_index for i in result.items] == [0, 1]
    assert result.items[0].clip_id == result.items[1].clip_id


def test_spelling_only_in_reviewed_slot_and_requires_every_letter(session):
    add(session, "HELLO")
    add(session, "A")
    pattern = approved(forms=["hello {name}"], glosses=["HELLO", "{name}"], fingerspellSlots=["name"])
    result = interpret(session, "hello ada", registry(pattern))
    assert result.status == "missing-signs"
    assert result.issues[0]["glosses"] == ["D"]
    assert all(not item.fingerspelled for item in result.items)
    add(session, "D")
    result = interpret(session, "hello ada", registry(pattern))
    assert result.status == "ready"
    assert [i.gloss for i in result.items] == ["HELLO", "A", "D", "A"]
    assert all(i.fingerspelled for i in result.items[1:])
    assert interpret(session, "ada", registry(pattern)).status == "unsupported"


def test_exact_phrase_beats_spelling_slot_and_ambiguity_blocks(session):
    add(session, "HELLO")
    add(session, "FATHER")
    exact = approved(forms=["hello father"], glosses=["HELLO", "FATHER"])
    general = approved(id="named", forms=["hello {name}"], glosses=["HELLO", "{name}"], fingerspellSlots=["name"])
    assert interpret(session, "hello father", registry(general, exact)).pattern_id == exact.id
    other = approved(id="other", forms=["hello father"], glosses=["FATHER"])
    result = interpret(session, "hello father", registry(exact, other))
    assert result.status == "unsupported" and result.issues[0]["code"] == "ambiguous-pattern"


def test_changed_recording_requires_new_review(session):
    add(session, "THANKYOU")
    father = add(session, "FATHER")
    father.content_hash = "new-timestamps"
    result = interpret(session, "thank you father", registry(approved()))
    assert result.status == "unsupported"
    assert result.issues[0]["code"] == "recording-review-required"


def test_default_sentence_interpretation_still_uses_reviewed_meaning(session, monkeypatch):
    from app.services import translate_service
    add(session, 'HELLO')
    monkeypatch.setattr(translate_service, 'load_registry', lambda: registry(
        Pattern(id='hello', forms=['hello'], glosses=['HELLO']),
    ))
    assert interpret(session, 'hello').status == 'unsupported'
    monkeypatch.setattr(translate_service, 'load_registry', lambda: registry(
        approved(forms=['hello'], glosses=['HELLO']),
    ))
    assert interpret(session, 'hello').status == 'ready'
