"""SQLAlchemy models for the CFS Log Exporter receiver."""

from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


DB_PATH = os.environ.get("DB_PATH", "./cfs_logs.db")


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    """A CFS session tracked by the exporter."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_uuid: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    pod_name: Mapped[str] = mapped_column(String, nullable=False)
    batcher_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cluster: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    xnames: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    playbooks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    log_lines: Mapped[list[LogLine]] = relationship(
        "LogLine", back_populates="session", cascade="all, delete-orphan"
    )


class LogLine(Base):
    """A single parsed log line belonging to a CFS session."""

    __tablename__ = "log_lines"
    __table_args__ = (
        Index("ix_log_lines_session_line", "session_id", "line_number"),
        Index("ix_log_lines_xname", "xname"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), index=True, nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    event_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    raw_line: Mapped[str] = mapped_column(Text, nullable=False)
    playbook: Mapped[str | None] = mapped_column(String, nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    play_name: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    task_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    xname: Mapped[str | None] = mapped_column(String, nullable=True)
    item: Mapped[str | None] = mapped_column(String, nullable=True)
    container: Mapped[str | None] = mapped_column(String, nullable=True)

    session: Mapped[SessionRecord] = relationship("SessionRecord", back_populates="log_lines")


def get_engine(db_path: str | None = None):
    """Create a SQLAlchemy engine for the configured SQLite database."""
    path = db_path or DB_PATH
    return create_engine(
        f"sqlite:///{path}",
        echo=False,
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )


def get_session_factory(db_path: str | None = None) -> sessionmaker[Session]:
    """Return a sessionmaker bound to the configured engine."""
    engine = get_engine(db_path)
    return sessionmaker(bind=engine)


def create_all(db_path: str | None = None) -> None:
    """Create all tables and apply lightweight migrations for existing DBs."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    # Add cluster column if missing (migration for existing databases)
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(sessions)"))]
        if "cluster" not in cols:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN cluster TEXT"))
            conn.commit()
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(log_lines)"))]
        if "container" not in cols:
            conn.execute(text("ALTER TABLE log_lines ADD COLUMN container TEXT"))
            conn.commit()
