"""FastAPI application for the CFS Log Exporter receiver."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

try:
    from models import LogLine, SessionRecord, create_all, get_session_factory
except ImportError:
    from receiver.models import LogLine, SessionRecord, create_all, get_session_factory

API_KEY = os.environ.get("API_KEY", "changeme")

# Staleness reconciler configuration
STALE_CHECK_INTERVAL = int(os.environ.get("STALE_CHECK_INTERVAL", "60"))  # seconds
STALE_THRESHOLD_MINUTES = int(os.environ.get("STALE_THRESHOLD_MINUTES", "15"))
MAX_STALE_CHECKS = int(os.environ.get("MAX_STALE_CHECKS", "6"))

log = logging.getLogger("cfs-receiver")

_session_factory = get_session_factory()


# ---------------------------------------------------------------------------
# Staleness reconciler
# ---------------------------------------------------------------------------

async def _reconcile_stale_sessions() -> None:
    """Periodically check for sessions stuck in 'running' and transition them.

    - If a 'running' session hasn't received new data for STALE_THRESHOLD_MINUTES,
      mark it as 'incomplete' and increment stale_checks.
    - If an 'incomplete' session has been checked MAX_STALE_CHECKS times with no
      new activity, mark it as 'unknown'.
    """
    while True:
        await asyncio.sleep(STALE_CHECK_INTERVAL)
        try:
            db = _session_factory()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_THRESHOLD_MINUTES)
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
                        log.info(
                            "Session %s marked incomplete (no activity for >%d min)",
                            session.session_uuid, STALE_THRESHOLD_MINUTES,
                        )
                    elif session.stale_checks >= MAX_STALE_CHECKS:
                        session.status = "unknown"
                        log.info(
                            "Session %s marked unknown after %d stale checks",
                            session.session_uuid, session.stale_checks,
                        )

                if stale:
                    db.commit()
            finally:
                db.close()
        except Exception as exc:
            log.warning("Stale session reconciler error: %s", exc)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    reconciler_task = asyncio.create_task(_reconcile_stale_sessions())
    yield
    reconciler_task.cancel()
    try:
        await reconciler_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="CFS Log Exporter Receiver", lifespan=lifespan)

# CORS – allow everything (internal tooling)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_db():
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()


def verify_token(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth.removeprefix("Bearer ").strip()
    if token != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SessionPayload(BaseModel):
    session_uuid: str
    pod_name: str
    batcher_id: str | None = None
    cluster: str | None = None
    xnames: list[str] = Field(default_factory=list)
    playbooks: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str = "running"


class EventPayload(BaseModel):
    event_type: str
    line_number: int
    raw_line: str
    timestamp: datetime | None = None
    playbook: str | None = None
    repo_url: str | None = None
    play_name: str | None = None
    role: str | None = None
    task_name: str | None = None
    status: str | None = None
    xname: str | None = None
    item: str | None = None
    container: str | None = None


class IngestBody(BaseModel):
    session: SessionPayload
    events: list[EventPayload] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/ingest", dependencies=[Depends(verify_token)])
def ingest(body: IngestBody, db: Session = Depends(get_db)):
    sp = body.session

    # Upsert session
    existing: SessionRecord | None = db.execute(
        select(SessionRecord).where(SessionRecord.session_uuid == sp.session_uuid)
    ).scalar_one_or_none()

    if existing is None:
        session_rec = SessionRecord(
            session_uuid=sp.session_uuid,
            pod_name=sp.pod_name,
            batcher_id=sp.batcher_id,
            cluster=sp.cluster,
            status=sp.status,
            started_at=sp.started_at,
            ended_at=sp.ended_at,
            xnames=sp.xnames,
            playbooks=sp.playbooks,
        )
        db.add(session_rec)
        db.flush()
    else:
        session_rec = existing
        session_rec.pod_name = sp.pod_name
        session_rec.batcher_id = sp.batcher_id or session_rec.batcher_id
        session_rec.cluster = sp.cluster or session_rec.cluster
        session_rec.status = sp.status
        session_rec.started_at = sp.started_at or session_rec.started_at
        session_rec.ended_at = sp.ended_at or session_rec.ended_at
        session_rec.updated_at = datetime.now(timezone.utc)
        session_rec.stale_checks = 0
        if sp.xnames:
            session_rec.xnames = sp.xnames
        if sp.playbooks:
            session_rec.playbooks = sp.playbooks
        db.flush()

    # Bulk insert log lines (skip duplicates by line_number within session)
    if body.events:
        existing_line_numbers: set[int] = set()
        if existing is not None:
            rows = db.execute(
                select(LogLine.line_number).where(LogLine.session_id == session_rec.id)
            ).scalars().all()
            existing_line_numbers = set(rows)

        new_lines = []
        for ev in body.events:
            if ev.line_number in existing_line_numbers:
                continue
            new_lines.append(
                LogLine(
                    session_id=session_rec.id,
                    line_number=ev.line_number,
                    timestamp=ev.timestamp,
                    event_type=ev.event_type,
                    raw_line=ev.raw_line,
                    playbook=ev.playbook,
                    repo_url=ev.repo_url,
                    play_name=ev.play_name,
                    role=ev.role,
                    task_name=ev.task_name,
                    status=ev.status,
                    xname=ev.xname,
                    item=ev.item,
                    container=ev.container,
                )
            )
            existing_line_numbers.add(ev.line_number)

        db.add_all(new_lines)
        lines_inserted = len(new_lines)
    else:
        lines_inserted = 0

    db.commit()
    return {"ok": True, "session_id": session_rec.id, "lines_inserted": lines_inserted}


@app.get("/api/sessions")
def list_sessions(
    xname: str | None = Query(None),
    status: str | None = Query(None),
    cluster: str | None = Query(None),
    session_name: str | None = Query(None),
    started_after: datetime | None = Query(None),
    started_before: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(SessionRecord)

    if cluster:
        stmt = stmt.where(SessionRecord.cluster == cluster)

    if status:
        stmt = stmt.where(SessionRecord.status == status)

    if session_name:
        stmt = stmt.where(SessionRecord.session_uuid.contains(session_name))

    if started_after:
        stmt = stmt.where(SessionRecord.started_at >= started_after)

    if started_before:
        stmt = stmt.where(SessionRecord.started_at <= started_before)

    # SQLite JSON: filter sessions whose xnames array contains the given xname
    # Supports glob wildcards (* and ?) for pattern matching
    if xname:
        if "*" in xname or "?" in xname:
            stmt = stmt.where(
                SessionRecord.id.in_(
                    select(SessionRecord.id)
                    .where(
                        text(
                            "EXISTS (SELECT 1 FROM json_each(sessions.xnames) WHERE json_each.value GLOB :xname)"
                        ).bindparams(xname=xname)
                    )
                )
            )
        else:
            stmt = stmt.where(
                SessionRecord.id.in_(
                    select(SessionRecord.id)
                    .where(
                        text(
                            "EXISTS (SELECT 1 FROM json_each(sessions.xnames) WHERE json_each.value = :xname)"
                        ).bindparams(xname=xname)
                    )
                )
            )

    stmt = stmt.order_by(SessionRecord.created_at.desc()).limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().unique().all()

    return [
        _session_to_dict(s)
        for s in rows
    ]


@app.get("/api/sessions/{session_uuid}")
def get_session(
    session_uuid: str,
    event_type: str | None = Query(None),
    xname: str | None = Query(None),
    container: str | None = Query(None),
    db: Session = Depends(get_db),
):
    session_rec: SessionRecord | None = db.execute(
        select(SessionRecord).where(SessionRecord.session_uuid == session_uuid)
    ).scalar_one_or_none()

    if session_rec is None:
        raise HTTPException(status_code=404, detail="Session not found")

    lines_stmt = (
        select(LogLine)
        .where(LogLine.session_id == session_rec.id)
        .order_by(LogLine.line_number)
    )
    if event_type:
        lines_stmt = lines_stmt.where(LogLine.event_type == event_type)
    if xname:
        lines_stmt = lines_stmt.where(LogLine.xname == xname)
    if container:
        lines_stmt = lines_stmt.where(LogLine.container == container)

    lines = db.execute(lines_stmt).scalars().all()

    result = _session_to_dict(session_rec)
    result["log_lines"] = [_line_to_dict(l) for l in lines]
    return result


@app.get("/api/sessions/{session_uuid}/stream")
async def stream_session(
    session_uuid: str,
    after_line: int = Query(0, ge=0),
):
    async def event_generator():
        last_line = after_line
        keepalive_counter = 0

        while True:
            db = _session_factory()
            try:
                session_rec: SessionRecord | None = db.execute(
                    select(SessionRecord).where(
                        SessionRecord.session_uuid == session_uuid
                    )
                ).scalar_one_or_none()

                if session_rec is None:
                    yield {"event": "error", "data": "Session not found"}
                    return

                lines = (
                    db.execute(
                        select(LogLine)
                        .where(
                            LogLine.session_id == session_rec.id,
                            LogLine.line_number > last_line,
                        )
                        .order_by(LogLine.line_number)
                    )
                    .scalars()
                    .all()
                )

                for line in lines:
                    yield {
                        "event": "log_line",
                        "data": _line_to_json(line),
                    }
                    last_line = line.line_number

                session_done = session_rec.status in ("completed", "failed", "incomplete", "unknown")
            finally:
                db.close()

            if session_done and not lines:
                yield {"event": "done", "data": "Session ended"}
                return

            keepalive_counter += 1
            if keepalive_counter >= 15:
                yield {"comment": "keepalive"}
                keepalive_counter = 0

            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())


@app.get("/api/clusters")
def list_clusters(db: Session = Depends(get_db)):
    """Return all distinct cluster names that have sent sessions."""
    rows = db.execute(
        select(SessionRecord.cluster)
        .where(SessionRecord.cluster.isnot(None))
        .distinct()
        .order_by(SessionRecord.cluster)
    ).scalars().all()
    return [{"cluster": r} for r in rows]


@app.get("/api/xnames")
def list_xnames(db: Session = Depends(get_db)):
    # Use json_each to explode xnames arrays, then count distinct sessions
    stmt = text(
        "SELECT je.value AS xname, COUNT(DISTINCT s.id) AS session_count "
        "FROM sessions s, json_each(s.xnames) je "
        "GROUP BY je.value "
        "ORDER BY je.value"
    )
    rows = db.execute(stmt).all()
    return [{"xname": row.xname, "session_count": row.session_count} for row in rows]


# ---------------------------------------------------------------------------
# Static files (frontend)
# ---------------------------------------------------------------------------

_app_dir = Path(__file__).resolve().parent
_static_candidates = [
    _app_dir / "static",                        # Docker: copied into app dir
    _app_dir.parent / "frontend" / "dist",      # Local dev: sibling frontend dir
]
for _candidate in _static_candidates:
    if _candidate.is_dir():
        app.mount("/", StaticFiles(directory=str(_candidate), html=True), name="frontend")
        break


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_to_dict(s: SessionRecord) -> dict[str, Any]:
    return {
        "id": s.id,
        "session_uuid": s.session_uuid,
        "pod_name": s.pod_name,
        "batcher_id": s.batcher_id,
        "cluster": s.cluster,
        "status": s.status,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "xnames": s.xnames,
        "playbooks": s.playbooks,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _line_to_dict(l: LogLine) -> dict[str, Any]:
    return {
        "id": l.id,
        "line_number": l.line_number,
        "timestamp": l.timestamp.isoformat() if l.timestamp else None,
        "event_type": l.event_type,
        "raw_line": l.raw_line,
        "playbook": l.playbook,
        "repo_url": l.repo_url,
        "play_name": l.play_name,
        "role": l.role,
        "task_name": l.task_name,
        "status": l.status,
        "xname": l.xname,
        "item": l.item,
        "container": l.container,
    }


def _line_to_json(l: LogLine) -> str:
    import json
    return json.dumps(_line_to_dict(l))
