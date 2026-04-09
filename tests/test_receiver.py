"""Integration tests for the CFS Log Receiver FastAPI app.

Run from project root:
    python3 -m pytest tests/test_receiver.py -v
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup – ensure `receiver/` is importable as a flat package so that
# app.py's `from models import ...` fallback (receiver.models) resolves, and
# also so that `from models import ...` works directly when sys.path includes
# the receiver directory.
# ---------------------------------------------------------------------------
_RECEIVER_DIR = Path(__file__).resolve().parent.parent / "receiver"
sys.path.insert(0, str(_RECEIVER_DIR))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

# Import app internals after path is configured
from receiver.models import Base, get_session_factory  # noqa: E402 – after path setup

# We import the app module itself via sys.path manipulation above, so the
# plain `from models import ...` inside app.py will now succeed.
import importlib
import receiver.app as _app_module

from receiver.app import app, get_db  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AUTH_HEADERS = {"Authorization": "Bearer changeme"}

SAMPLE_PAYLOAD = {
    "session": {
        "session_uuid": "test-uuid-1234",
        "pod_name": "cfs-test-uuid-1234-abc",
        "batcher_id": "batch-001",
        "xnames": ["x1000c0s0b0n0", "x1000c0s1b0n0"],
        "playbooks": ["test.yml"],
        "started_at": "2026-04-07T10:00:00",
        "ended_at": None,
        "status": "running",
    },
    "events": [
        {
            "event_type": "playbook_start",
            "line_number": 1,
            "raw_line": "Running test.yml from repo https://example.com",
            "playbook": "test.yml",
        },
        {
            "event_type": "task_result",
            "line_number": 2,
            "raw_line": "changed: [x1000c0s0b0n0]",
            "status": "changed",
            "xname": "x1000c0s0b0n0",
        },
    ],
}


@pytest.fixture()
def db_session_factory(tmp_path):
    """Create a fresh SQLite database in tmp_path and return a sessionmaker."""
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture()
def client(db_session_factory):
    """Return a TestClient whose get_db dependency uses the test database."""

    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def ingest(client: TestClient, payload: dict | None = None, headers: dict | None = None):
    """POST to /api/ingest with optional payload/header overrides."""
    payload = payload or SAMPLE_PAYLOAD
    headers = headers if headers is not None else AUTH_HEADERS
    return client.post("/api/ingest", json=payload, headers=headers)


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_200(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_returns_status_ok(self, client):
        response = client.get("/api/health")
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /api/ingest
# ---------------------------------------------------------------------------

class TestIngest:
    def test_valid_payload_returns_200(self, client):
        response = ingest(client)
        assert response.status_code == 200

    def test_valid_payload_returns_ok_true(self, client):
        response = ingest(client)
        assert response.json()["ok"] is True

    def test_valid_payload_returns_correct_lines_inserted(self, client):
        response = ingest(client)
        assert response.json()["lines_inserted"] == 2

    def test_valid_payload_creates_session_id(self, client):
        response = ingest(client)
        assert response.json()["session_id"] is not None

    def test_missing_bearer_token_returns_401(self, client):
        response = ingest(client, headers={})
        assert response.status_code == 401

    def test_wrong_bearer_token_returns_403(self, client):
        response = ingest(client, headers={"Authorization": "Bearer wrongkey"})
        assert response.status_code == 403

    def test_duplicate_batch_inserts_zero_new_lines(self, client):
        ingest(client)
        second = ingest(client)
        assert second.json()["lines_inserted"] == 0

    def test_duplicate_batch_does_not_create_extra_session(self, client):
        first = ingest(client)
        second = ingest(client)
        assert first.json()["session_id"] == second.json()["session_id"]

    def test_updates_session_status_on_re_post(self, client):
        ingest(client)
        updated_payload = {
            **SAMPLE_PAYLOAD,
            "session": {**SAMPLE_PAYLOAD["session"], "status": "completed"},
            "events": [],
        }
        ingest(client, payload=updated_payload)
        response = client.get(f"/api/sessions/{SAMPLE_PAYLOAD['session']['session_uuid']}")
        assert response.json()["status"] == "completed"

    def test_payload_with_no_events_inserts_zero_lines(self, client):
        payload = {**SAMPLE_PAYLOAD, "events": []}
        response = ingest(client, payload=payload)
        assert response.json()["lines_inserted"] == 0

    def test_partial_duplicate_only_inserts_new_lines(self, client):
        """Re-posting with one existing line and one new line inserts only the new one."""
        ingest(client)
        payload_with_extra = {
            **SAMPLE_PAYLOAD,
            "events": [
                *SAMPLE_PAYLOAD["events"],
                {
                    "event_type": "task_result",
                    "line_number": 3,
                    "raw_line": "ok: [x1000c0s1b0n0]",
                    "status": "ok",
                    "xname": "x1000c0s1b0n0",
                },
            ],
        }
        response = ingest(client, payload=payload_with_extra)
        assert response.json()["lines_inserted"] == 1


# ---------------------------------------------------------------------------
# GET /api/sessions
# ---------------------------------------------------------------------------

class TestListSessions:
    def test_returns_empty_list_when_no_sessions(self, client):
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_list_after_ingest(self, client):
        ingest(client)
        response = client.get("/api/sessions")
        assert len(response.json()) == 1

    def test_filter_by_status_returns_matching_sessions(self, client):
        ingest(client)
        response = client.get("/api/sessions?status=running")
        assert len(response.json()) == 1
        assert response.json()[0]["status"] == "running"

    def test_filter_by_status_excludes_non_matching_sessions(self, client):
        ingest(client)
        response = client.get("/api/sessions?status=completed")
        assert response.json() == []

    def test_filter_by_xname_returns_matching_sessions(self, client):
        ingest(client)
        response = client.get("/api/sessions?xname=x1000c0s0b0n0")
        assert len(response.json()) == 1

    def test_filter_by_xname_excludes_sessions_without_that_xname(self, client):
        ingest(client)
        response = client.get("/api/sessions?xname=x9999c0s0b0n0")
        assert response.json() == []

    def test_session_record_contains_expected_fields(self, client):
        ingest(client)
        session = client.get("/api/sessions").json()[0]
        for field in ("id", "session_uuid", "pod_name", "status", "xnames", "playbooks"):
            assert field in session


# ---------------------------------------------------------------------------
# GET /api/sessions/{uuid}
# ---------------------------------------------------------------------------

class TestGetSession:
    def test_returns_session_with_log_lines(self, client):
        ingest(client)
        response = client.get(f"/api/sessions/{SAMPLE_PAYLOAD['session']['session_uuid']}")
        assert response.status_code == 200
        data = response.json()
        assert "log_lines" in data
        assert len(data["log_lines"]) == 2

    def test_returns_404_for_nonexistent_session(self, client):
        response = client.get("/api/sessions/does-not-exist-uuid")
        assert response.status_code == 404

    def test_log_lines_ordered_by_line_number(self, client):
        ingest(client)
        data = client.get(f"/api/sessions/{SAMPLE_PAYLOAD['session']['session_uuid']}").json()
        line_numbers = [ll["line_number"] for ll in data["log_lines"]]
        assert line_numbers == sorted(line_numbers)

    def test_filter_log_lines_by_event_type(self, client):
        ingest(client)
        uuid = SAMPLE_PAYLOAD["session"]["session_uuid"]
        response = client.get(f"/api/sessions/{uuid}?event_type=playbook_start")
        lines = response.json()["log_lines"]
        assert len(lines) == 1
        assert lines[0]["event_type"] == "playbook_start"

    def test_filter_log_lines_by_event_type_returns_none_when_no_match(self, client):
        ingest(client)
        uuid = SAMPLE_PAYLOAD["session"]["session_uuid"]
        response = client.get(f"/api/sessions/{uuid}?event_type=nonexistent_type")
        assert response.json()["log_lines"] == []

    def test_filter_log_lines_by_xname(self, client):
        ingest(client)
        uuid = SAMPLE_PAYLOAD["session"]["session_uuid"]
        response = client.get(f"/api/sessions/{uuid}?xname=x1000c0s0b0n0")
        lines = response.json()["log_lines"]
        assert all(ll["xname"] == "x1000c0s0b0n0" for ll in lines)

    def test_session_uuid_matches_requested_uuid(self, client):
        ingest(client)
        uuid = SAMPLE_PAYLOAD["session"]["session_uuid"]
        data = client.get(f"/api/sessions/{uuid}").json()
        assert data["session_uuid"] == uuid


# ---------------------------------------------------------------------------
# GET /api/xnames
# ---------------------------------------------------------------------------

class TestListXnames:
    def test_returns_empty_list_when_no_sessions(self, client):
        response = client.get("/api/xnames")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_xnames_after_ingest(self, client):
        ingest(client)
        response = client.get("/api/xnames")
        xnames = [entry["xname"] for entry in response.json()]
        assert "x1000c0s0b0n0" in xnames
        assert "x1000c0s1b0n0" in xnames

    def test_each_entry_has_session_count(self, client):
        ingest(client)
        for entry in client.get("/api/xnames").json():
            assert "xname" in entry
            assert "session_count" in entry

    def test_session_count_is_one_for_single_session(self, client):
        ingest(client)
        for entry in client.get("/api/xnames").json():
            assert entry["session_count"] == 1

    def test_session_count_increments_for_second_session_sharing_xname(self, client):
        ingest(client)
        second_payload = {
            "session": {
                **SAMPLE_PAYLOAD["session"],
                "session_uuid": "another-uuid-5678",
                "pod_name": "cfs-another-uuid-5678-xyz",
                "xnames": ["x1000c0s0b0n0"],  # shares one xname with first session
            },
            "events": [],
        }
        ingest(client, payload=second_payload)
        entries = {e["xname"]: e["session_count"] for e in client.get("/api/xnames").json()}
        assert entries["x1000c0s0b0n0"] == 2

    def test_xnames_are_returned_sorted(self, client):
        ingest(client)
        xnames = [entry["xname"] for entry in client.get("/api/xnames").json()]
        assert xnames == sorted(xnames)
