"""Tests for the staleness reconciler logic."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import SessionRecord, Base


@pytest.fixture
def db():
    """In-memory SQLite database for each test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()


def _make_session(db, uuid, status="running", updated_minutes_ago=0, stale_checks=0):
    """Helper to insert a session with a controlled updated_at."""
    now = datetime.now(timezone.utc)
    s = SessionRecord(
        session_uuid=uuid,
        pod_name=f"cfs-{uuid}-abc",
        status=status,
        updated_at=now - timedelta(minutes=updated_minutes_ago),
        stale_checks=stale_checks,
        xnames=[],
        playbooks=[],
    )
    db.add(s)
    db.commit()
    return s


class TestReconcilerLogic:
    """Test the reconciler state transitions directly (no async task)."""

    def _reconcile(self, db, stale_threshold_minutes=15, max_stale_checks=6):
        """Run the reconciler logic synchronously against the given db session."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_minutes)
        stale = db.execute(
            select(SessionRecord).where(
                SessionRecord.status.in_(["running", "incomplete"]),
                SessionRecord.updated_at < cutoff,
            )
        ).scalars().all()

        for session in stale:
            session.stale_checks += 1
            if session.status == "running":
                session.status = "incomplete"
            elif session.stale_checks >= max_stale_checks:
                session.status = "unknown"

        if stale:
            db.commit()

    def test_running_session_not_stale(self, db):
        """A running session with recent activity should not be touched."""
        _make_session(db, "aaa", status="running", updated_minutes_ago=5)
        self._reconcile(db)
        s = db.execute(select(SessionRecord)).scalar_one()
        assert s.status == "running"
        assert s.stale_checks == 0

    def test_running_becomes_incomplete(self, db):
        """A running session with no activity beyond threshold becomes incomplete."""
        _make_session(db, "bbb", status="running", updated_minutes_ago=20)
        self._reconcile(db)
        s = db.execute(select(SessionRecord)).scalar_one()
        assert s.status == "incomplete"
        assert s.stale_checks == 1

    def test_incomplete_stays_incomplete_until_max_checks(self, db):
        """An incomplete session stays incomplete until max stale checks."""
        _make_session(db, "ccc", status="incomplete", updated_minutes_ago=20, stale_checks=3)
        self._reconcile(db)
        s = db.execute(select(SessionRecord)).scalar_one()
        assert s.status == "incomplete"
        assert s.stale_checks == 4

    def test_incomplete_becomes_unknown_at_max_checks(self, db):
        """An incomplete session becomes unknown after max stale checks."""
        _make_session(db, "ddd", status="incomplete", updated_minutes_ago=20, stale_checks=5)
        self._reconcile(db)
        s = db.execute(select(SessionRecord)).scalar_one()
        assert s.status == "unknown"
        assert s.stale_checks == 6

    def test_completed_not_affected(self, db):
        """Completed sessions should never be touched by the reconciler."""
        _make_session(db, "eee", status="completed", updated_minutes_ago=60)
        self._reconcile(db)
        s = db.execute(select(SessionRecord)).scalar_one()
        assert s.status == "completed"
        assert s.stale_checks == 0

    def test_failed_not_affected(self, db):
        """Failed sessions should never be touched by the reconciler."""
        _make_session(db, "fff", status="failed", updated_minutes_ago=60)
        self._reconcile(db)
        s = db.execute(select(SessionRecord)).scalar_one()
        assert s.status == "failed"
        assert s.stale_checks == 0

    def test_unknown_not_affected(self, db):
        """Unknown sessions should not be re-processed."""
        _make_session(db, "ggg", status="unknown", updated_minutes_ago=60, stale_checks=6)
        self._reconcile(db)
        s = db.execute(select(SessionRecord)).scalar_one()
        assert s.status == "unknown"
        assert s.stale_checks == 6

    def test_multiple_sessions_mixed(self, db):
        """Multiple sessions at different states are handled correctly."""
        _make_session(db, "h1", status="running", updated_minutes_ago=5)   # fresh, keep
        _make_session(db, "h2", status="running", updated_minutes_ago=20)  # stale, → incomplete
        _make_session(db, "h3", status="incomplete", updated_minutes_ago=20, stale_checks=5)  # → unknown
        _make_session(db, "h4", status="completed", updated_minutes_ago=60)  # terminal, skip

        self._reconcile(db)

        sessions = {s.session_uuid: s for s in db.execute(select(SessionRecord)).scalars().all()}
        assert sessions["h1"].status == "running"
        assert sessions["h2"].status == "incomplete"
        assert sessions["h3"].status == "unknown"
        assert sessions["h4"].status == "completed"

    def test_stale_checks_reset_on_new_activity(self, db):
        """Simulates new ingest resetting stale_checks (as the ingest endpoint does)."""
        s = _make_session(db, "iii", status="incomplete", updated_minutes_ago=20, stale_checks=3)
        # Simulate ingest arriving
        s.status = "running"
        s.stale_checks = 0
        s.updated_at = datetime.now(timezone.utc)
        db.commit()

        self._reconcile(db)
        s = db.execute(select(SessionRecord)).scalar_one()
        assert s.status == "running"
        assert s.stale_checks == 0
