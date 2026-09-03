from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class RigProfileRow(Base):
    __tablename__ = "rig_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    digest: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    avatar_name: Mapped[str] = mapped_column(String(128))
    hip_height: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class Gloss(Base):
    """One lexical item in the sign vocabulary."""

    __tablename__ = "glosses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    english: Mapped[str] = mapped_column(String(256), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    clips: Mapped[list["SignClip"]] = relationship(back_populates="gloss")


class SignClip(Base):
    """One retargeted take. A gloss may have several; exactly one is canonical."""

    __tablename__ = "sign_clips"
    __table_args__ = (UniqueConstraint("gloss_id", "take", name="uq_gloss_take"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    gloss_id: Mapped[int] = mapped_column(ForeignKey("glosses.id"), index=True)
    rig_digest: Mapped[str] = mapped_column(String(32), index=True)

    take: Mapped[int] = mapped_column(Integer, default=1)
    is_canonical: Mapped[bool] = mapped_column(default=False)

    source_csv: Mapped[str] = mapped_column(String(512))
    clip_path: Mapped[str] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    fps: Mapped[float] = mapped_column(Float)
    frame_count: Mapped[int] = mapped_column(Integer)
    duration: Mapped[float] = mapped_column(Float)
    byte_size: Mapped[int] = mapped_column(Integer)

    qc: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    gloss: Mapped[Gloss] = relationship(back_populates="clips")


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    gloss_name: Mapped[str] = mapped_column(String(64))
    source_csv: Mapped[str] = mapped_column(String(512))
    clip_id: Mapped[int | None] = mapped_column(ForeignKey("sign_clips.id"), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    qc: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
