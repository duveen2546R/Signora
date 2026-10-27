import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.video import youtube_video_id
from app.core.db import Base
from app.models import Gloss, SignClip
from app.services.video_plan_service import resolve_caption


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as value:
        yield value


def add(session, name, english=""):
    gloss = Gloss(name=name, english=english)
    session.add(gloss)
    session.flush()
    session.add(SignClip(
        gloss_id=gloss.id, rig_digest="d" * 16, take=1, is_canonical=True,
        source_csv="x.fbx", clip_path="x.signclip", content_hash=name.lower(),
        fps=60, frame_count=60, duration=1, byte_size=1, qc={},
    ))
    session.flush()


def test_caption_policy_removes_articles_but_keeps_content_sign(session):
    add(session, "FATHER", "father")
    result = resolve_caption(session, "the father")
    assert result.status == "literal-preview"
    assert [item.gloss for item in result.items] == ["FATHER"]


def test_unknown_word_skips_whole_unit_when_alphabet_is_incomplete(session):
    add(session, "FATHER", "father")
    add(session, "X", "")
    result = resolve_caption(session, "father xyz")
    assert result.status == "unsupported"
    assert result.items == []
    assert result.unmapped == ["xyz"]


def test_fingerspelling_is_allowed_only_with_complete_alphabet(session):
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        add(session, letter)
    result = resolve_caption(session, "cat")
    assert [item.gloss for item in result.items] == ["C", "A", "T"]
    assert all(item.fingerspelled for item in result.items)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?t=2",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "dQw4w9WgXcQ",
])
def test_youtube_url_forms(url):
    assert youtube_video_id(url) == "dQw4w9WgXcQ"


def test_non_youtube_url_is_rejected():
    with pytest.raises(ValueError):
        youtube_video_id("https://example.com/watch?v=dQw4w9WgXcQ")
