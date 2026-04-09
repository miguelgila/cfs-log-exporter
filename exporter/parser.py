"""
Ansible CFS Log Parser

Parses raw CFS Ansible log output into structured events.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class EventType(str, Enum):
    PLAYBOOK_START = "playbook_start"
    PLAY_START = "play_start"
    TASK_START = "task_start"
    TASK_RESULT = "task_result"
    PLAY_RECAP = "play_recap"
    RECAP_HOST = "recap_host"
    INFO = "info"
    WARNING = "warning"


class TaskStatus(str, Enum):
    OK = "ok"
    CHANGED = "changed"
    FAILED = "failed"
    FATAL = "fatal"
    SKIPPING = "skipping"
    UNREACHABLE = "unreachable"


@dataclass
class LogEvent:
    event_type: EventType
    line_number: int
    raw_line: str
    timestamp: Optional[datetime] = None
    playbook: Optional[str] = None
    repo_url: Optional[str] = None
    play_name: Optional[str] = None
    role: Optional[str] = None
    task_name: Optional[str] = None
    status: Optional[str] = None
    xname: Optional[str] = None
    item: Optional[str] = None
    container: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "event_type": self.event_type.value,
            "line_number": self.line_number,
            "raw_line": self.raw_line,
        }
        if self.timestamp:
            d["timestamp"] = self.timestamp.isoformat()
        if self.playbook:
            d["playbook"] = self.playbook
        if self.repo_url:
            d["repo_url"] = self.repo_url
        if self.play_name:
            d["play_name"] = self.play_name
        if self.role:
            d["role"] = self.role
        if self.task_name:
            d["task_name"] = self.task_name
        if self.status:
            d["status"] = self.status
        if self.xname:
            d["xname"] = self.xname
        if self.item:
            d["item"] = self.item
        if self.container:
            d["container"] = self.container
        return d


@dataclass
class SessionInfo:
    session_id: str
    pod_name: str
    xnames: list[str] = field(default_factory=list)
    playbooks: list[str] = field(default_factory=list)
    batcher_id: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "pod_name": self.pod_name,
            "xnames": self.xnames,
            "playbooks": self.playbooks,
            "batcher_id": self.batcher_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }


# Regex patterns
RE_PLAYBOOK_START = re.compile(
    r"^Running (\S+\.yml) from repo (.+)$"
)
RE_PLAY = re.compile(
    r"^PLAY \[(.+?)\] \*+"
)
RE_TASK = re.compile(
    r"^TASK \[(.+?)\] \*+"
)
RE_TASK_RESULT = re.compile(
    r"^(ok|changed|failed|fatal|skipping|unreachable): \[([^\]]+)\]"
)
RE_TASK_RESULT_ITEM = re.compile(
    r"^(ok|changed|failed|fatal|skipping|unreachable): \[([^\]]+)\] => \(item=([^)]+)\)"
)
RE_PLAY_RECAP = re.compile(
    r"^PLAY RECAP \*+"
)
RE_RECAP_HOST = re.compile(
    r"^(\S+)\s+:\s+(ok=\d+.*)"
)
RE_TIMESTAMP = re.compile(
    r"^(\w+ \d{2} \w+ \d{4})\s+(\d{2}:\d{2}:\d{2}) \+\d{4}"
)
RE_XNAME = re.compile(
    r"x\d+c\d+s\d+b\d+n\d+"
)
RE_SUBSET = re.compile(
    r"subset:([\w,]+)"
)
RE_BATCHER = re.compile(
    r"batcher-([0-9a-f-]+)"
)
RE_WARNING = re.compile(
    r"^\[WARNING\]"
)
RE_SESSION_ID = re.compile(
    r"^cfs-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


def extract_session_id(pod_name: str) -> str:
    """Extract CFS session UUID from pod name like cfs-<uuid>-<suffix>."""
    m = RE_SESSION_ID.match(pod_name)
    if m:
        return m.group(1)
    return pod_name


class CFSLogParser:
    """Stateful parser that tracks context across log lines."""

    def __init__(self, pod_name: str = "unknown"):
        self.pod_name = pod_name
        self.session_id = extract_session_id(pod_name)
        self.current_playbook: Optional[str] = None
        self.current_repo: Optional[str] = None
        self.current_play: Optional[str] = None
        self.current_role: Optional[str] = None
        self.current_task: Optional[str] = None
        self.last_timestamp: Optional[datetime] = None
        self.xnames: set[str] = set()
        self.playbooks: list[str] = []
        self.batcher_id: Optional[str] = None
        self.first_timestamp: Optional[datetime] = None
        self.last_seen_timestamp: Optional[datetime] = None
        self._in_play_recap: bool = False

    def parse_line(self, line_number: int, line: str) -> Optional[LogEvent]:
        """Parse a single log line and return a structured event, or None for noise."""
        line = line.rstrip()
        if not line:
            return None

        # Try to extract timestamp from any line
        ts_match = RE_TIMESTAMP.match(line)
        if ts_match:
            try:
                ts = datetime.strptime(
                    f"{ts_match.group(1)} {ts_match.group(2)}",
                    "%A %d %B %Y %H:%M:%S",
                ).replace(tzinfo=timezone.utc)
                self.last_timestamp = ts
                self.last_seen_timestamp = ts
                if self.first_timestamp is None:
                    self.first_timestamp = ts
            except ValueError:
                pass
            # Timestamp-only lines are noise, skip them
            return None

        # Extract batcher ID if we haven't yet
        if self.batcher_id is None:
            batcher_match = RE_BATCHER.search(line)
            if batcher_match:
                self.batcher_id = batcher_match.group(1)

        # Extract xnames from subset lines
        subset_match = RE_SUBSET.search(line)
        if subset_match:
            names = subset_match.group(1).split(",")
            for n in names:
                if RE_XNAME.match(n):
                    self.xnames.add(n)

        # Playbook start
        m = RE_PLAYBOOK_START.match(line)
        if m:
            self.current_playbook = m.group(1)
            self.current_repo = m.group(2)
            self.current_play = None
            self.current_task = None
            self.current_role = None
            if self.current_playbook not in self.playbooks:
                self.playbooks.append(self.current_playbook)
            return LogEvent(
                event_type=EventType.PLAYBOOK_START,
                line_number=line_number,
                raw_line=line,
                timestamp=self.last_timestamp,
                playbook=self.current_playbook,
                repo_url=self.current_repo,
            )

        # Play start
        m = RE_PLAY.match(line)
        if m:
            self.current_play = m.group(1)
            self.current_task = None
            self.current_role = None
            return LogEvent(
                event_type=EventType.PLAY_START,
                line_number=line_number,
                raw_line=line,
                timestamp=self.last_timestamp,
                playbook=self.current_playbook,
                play_name=self.current_play,
            )

        # Task start
        m = RE_TASK.match(line)
        if m:
            task_full = m.group(1)
            if " : " in task_full:
                self.current_role, self.current_task = task_full.split(" : ", 1)
            else:
                self.current_role = None
                self.current_task = task_full
            return LogEvent(
                event_type=EventType.TASK_START,
                line_number=line_number,
                raw_line=line,
                timestamp=self.last_timestamp,
                playbook=self.current_playbook,
                play_name=self.current_play,
                role=self.current_role,
                task_name=self.current_task,
            )

        # Task result with item
        m = RE_TASK_RESULT_ITEM.match(line)
        if m:
            status_str, target, item = m.group(1), m.group(2), m.group(3)
            status = TaskStatus(status_str)
            xname = target if RE_XNAME.fullmatch(target) else None
            if xname:
                self.xnames.add(xname)
            return LogEvent(
                event_type=EventType.TASK_RESULT,
                line_number=line_number,
                raw_line=line,
                timestamp=self.last_timestamp,
                playbook=self.current_playbook,
                play_name=self.current_play,
                role=self.current_role,
                task_name=self.current_task,
                status=status,
                xname=xname,
                item=item,
            )

        # Task result without item
        m = RE_TASK_RESULT.match(line)
        if m:
            status_str, target = m.group(1), m.group(2)
            status = TaskStatus(status_str)
            xname = target if RE_XNAME.fullmatch(target) else None
            if xname:
                self.xnames.add(xname)
            return LogEvent(
                event_type=EventType.TASK_RESULT,
                line_number=line_number,
                raw_line=line,
                timestamp=self.last_timestamp,
                playbook=self.current_playbook,
                play_name=self.current_play,
                role=self.current_role,
                task_name=self.current_task,
                status=status,
                xname=xname,
            )

        # Play recap header
        m = RE_PLAY_RECAP.match(line)
        if m:
            self._in_play_recap = True
            return LogEvent(
                event_type=EventType.PLAY_RECAP,
                line_number=line_number,
                raw_line=line,
                timestamp=self.last_timestamp,
                playbook=self.current_playbook,
            )

        # Recap host line (per-host summary after PLAY RECAP ***)
        if self._in_play_recap:
            m = RE_RECAP_HOST.match(line)
            if m:
                hostname = m.group(1)
                counts = m.group(2).strip()
                xname = hostname if RE_XNAME.fullmatch(hostname) else None
                if xname:
                    self.xnames.add(xname)
                return LogEvent(
                    event_type=EventType.RECAP_HOST,
                    line_number=line_number,
                    raw_line=line,
                    timestamp=self.last_timestamp,
                    playbook=self.current_playbook,
                    xname=xname or hostname,
                    status=counts,
                )
            else:
                # Non-recap-host line ends the recap section
                self._in_play_recap = False

        # Warning
        if RE_WARNING.match(line):
            return LogEvent(
                event_type=EventType.WARNING,
                line_number=line_number,
                raw_line=line,
                timestamp=self.last_timestamp,
                playbook=self.current_playbook,
            )

        # Skip noisy lines (Failed to patch, curl output, separators, etc.)
        if any(line.startswith(p) for p in (
            "Failed to patch",
            "  %",
            "HTTP/",
            "content-type:",
            "cache-control:",
            "x-content-type-options:",
            "date:",
            "server:",
            "transfer-encoding:",
            "~~~",
            "===",
            "---",
            "total ---",
            "Playbook run took",
        )):
            return None

        # General info line (sidecar available, inventory, SSH keys, etc.)
        if line.strip():
            return LogEvent(
                event_type=EventType.INFO,
                line_number=line_number,
                raw_line=line,
                timestamp=self.last_timestamp,
                playbook=self.current_playbook,
            )

        return None

    def get_session_info(self) -> SessionInfo:
        """Return accumulated session metadata."""
        return SessionInfo(
            session_id=self.session_id,
            pod_name=self.pod_name,
            xnames=sorted(self.xnames),
            playbooks=self.playbooks,
            batcher_id=self.batcher_id,
            started_at=self.first_timestamp,
            ended_at=self.last_seen_timestamp,
        )

    def parse_file(self, filepath: str) -> tuple[SessionInfo, list[LogEvent]]:
        """Parse an entire log file. Returns session info and list of events."""
        events = []
        with open(filepath, "r") as f:
            for i, line in enumerate(f, start=1):
                event = self.parse_line(i, line)
                if event:
                    events.append(event)
        return self.get_session_info(), events


if __name__ == "__main__":
    import json
    import sys

    filepath = sys.argv[1] if len(sys.argv) > 1 else "cfs-log.txt"
    pod_name = sys.argv[2] if len(sys.argv) > 2 else "cfs-c452edd0-7b87-4af1-b4c4-65d988cc694b-k92xrc"

    parser = CFSLogParser(pod_name=pod_name)
    session, events = parser.parse_file(filepath)

    print(f"Session: {session.session_id}")
    print(f"Pod: {session.pod_name}")
    print(f"Batcher: {session.batcher_id}")
    print(f"Xnames ({len(session.xnames)}): {', '.join(session.xnames[:5])}...")
    print(f"Playbooks ({len(session.playbooks)}): {', '.join(session.playbooks)}")
    print(f"Time: {session.started_at} -> {session.ended_at}")
    print(f"Total events: {len(events)}")
    print()

    # Count by type
    from collections import Counter
    type_counts = Counter(e.event_type.value for e in events)
    print("Events by type:")
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")

    # Count task results by status
    status_counts = Counter(
        e.status.value for e in events if e.status
    )
    print("\nTask results by status:")
    for s, c in status_counts.most_common():
        print(f"  {s}: {c}")

    # Show unique xnames from task results
    result_xnames = set(e.xname for e in events if e.xname)
    print(f"\nUnique xnames in results: {len(result_xnames)}")
