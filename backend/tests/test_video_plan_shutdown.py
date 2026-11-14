"""Stopping the server mid-preparation: Ctrl+C is not held open, and no plan is left "processing"."""
import time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.models import VideoPlan, VideoPlanUnit
from app.services import video_plan_service

# The autouse fixture in conftest disables recovery for app start-ups; these tests call the real one.
RECOVER = video_plan_service.recover_interrupted_plans


@pytest.fixture
def factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(video_plan_service, "SessionLocal", factory)
    yield factory
    video_plan_service._stopping.clear()


def add_plan(factory, status, units=2):
    with factory() as session:
        plan = VideoPlan(
            id=f"plan-{status}-{time.monotonic_ns()}", youtube_video_id="bobPMUfr_c0", subtitle_hash="h",
            status=status, policy_version=1, pattern_version=1, library_version="v",
            motion_algorithm_version=1, total_units=units,
        )
        for ordinal in range(units):
            plan.units.append(VideoPlanUnit(
                ordinal=ordinal, start_ms=ordinal * 1000, end_ms=ordinal * 1000 + 900,
                source_text="hello", normalized_text="hello", source_cue_ids=[str(ordinal)],
            ))
        session.add(plan)
        session.commit()
        return plan.id


def status_of(factory, plan_id):
    with factory() as session:
        plan = session.get(VideoPlan, plan_id)
        return plan.status, plan.error


def test_plans_interrupted_by_a_restart_are_failed_on_startup(factory):
    pending, processing, ready = (add_plan(factory, s) for s in ("pending", "processing", "ready"))
    assert RECOVER() == 2
    assert status_of(factory, pending) == ("failed", video_plan_service.INTERRUPTED_ERROR)
    assert status_of(factory, processing) == ("failed", video_plan_service.INTERRUPTED_ERROR)
    assert status_of(factory, ready)[0] == "ready"


def test_shutdown_stops_preparation_at_the_next_unit(factory, monkeypatch):
    plan_id = add_plan(factory, "pending", units=3)
    seen = []

    def slow_caption(session, text):
        seen.append(text)
        video_plan_service._stopping.set()  # Ctrl+C arrives while the first unit is composing
        return original(session, text)

    original = video_plan_service.resolve_caption
    monkeypatch.setattr(video_plan_service, "resolve_caption", slow_caption)
    video_plan_service.prepare_plan(plan_id)
    assert len(seen) == 1, "no further unit is started after shutdown begins"
    assert status_of(factory, plan_id) == ("failed", video_plan_service.INTERRUPTED_ERROR)


def test_stop_preparations_returns_promptly_and_workers_are_daemons(factory, monkeypatch):
    plan_id = add_plan(factory, "pending", units=50)

    def slow_caption(session, text):
        time.sleep(0.05)
        return original(session, text)

    original = video_plan_service.resolve_caption
    monkeypatch.setattr(video_plan_service, "resolve_caption", slow_caption)
    worker = video_plan_service.start_preparation(plan_id)
    assert worker.daemon, "a worker can never keep the process alive after shutdown"
    time.sleep(0.1)
    started = time.monotonic()
    video_plan_service.stop_preparations(timeout=5)
    assert time.monotonic() - started < 2
    assert not worker.is_alive()
    assert status_of(factory, plan_id) == ("failed", video_plan_service.INTERRUPTED_ERROR)
