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
    """One normalized motion take. A gloss may have several; exactly one is canonical.

    `source_csv` and `clip_path` retain their original database column names so existing local
    libraries migrate without destructive schema changes; new rows point to FBX and motion JSON.
    """

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


class LiveMotionArtifact(Base):
    """A persistent, quality-gated single-sign or directed-pair composition."""

    __tablename__ = "live_motion_artifacts"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    library_version: Mapped[str] = mapped_column(String(64), index=True)
    from_clip_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    to_clip_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    algorithm_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), index=True)
    artifact_path: Mapped[str] = mapped_column(String(512), default="")
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class VideoPlan(Base):
    """A subtitle-derived signing plan for one YouTube video."""

    __tablename__ = "video_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(11), index=True)
    subtitle_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    language: Mapped[str] = mapped_column(String(16), default="ISL")
    policy_version: Mapped[int] = mapped_column(Integer)
    pattern_version: Mapped[int] = mapped_column(Integer)
    library_version: Mapped[str] = mapped_column(String(64), index=True)
    motion_algorithm_version: Mapped[int] = mapped_column(Integer)
    total_units: Mapped[int] = mapped_column(Integer, default=0)
    signed_units: Mapped[int] = mapped_column(Integer, default=0)
    fingerspelled_units: Mapped[int] = mapped_column(Integer, default=0)
    function_only_units: Mapped[int] = mapped_column(Integer, default=0)
    unsupported_units: Mapped[int] = mapped_column(Integer, default=0)
    coverage: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    units: Mapped[list["VideoPlanUnit"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="VideoPlanUnit.ordinal"
    )


class VideoPlanUnit(Base):
    __tablename__ = "video_plan_units"
    __table_args__ = (UniqueConstraint("plan_id", "ordinal", name="uq_video_plan_unit"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("video_plans.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    glosses: Mapped[list] = mapped_column(JSON, default=list)
    fingerspelled_words: Mapped[list] = mapped_column(JSON, default=list)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    source_cue_ids: Mapped[list] = mapped_column(JSON, default=list)
    motion_path: Mapped[str] = mapped_column(String(512), default="")
    motion_duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    plan: Mapped[VideoPlan] = relationship(back_populates="units")
