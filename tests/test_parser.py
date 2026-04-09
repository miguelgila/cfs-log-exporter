"""
Unit tests for exporter/parser.py
"""

import os
import pytest
from datetime import datetime, timezone

from exporter.parser import (
    CFSLogParser,
    EventType,
    LogEvent,
    SessionInfo,
    TaskStatus,
    extract_session_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_LOG = os.path.join(
    os.path.dirname(__file__), "..", "cfs-log.txt"
)
REAL_POD_NAME = "cfs-c452edd0-7b87-4af1-b4c4-65d988cc694b-k92xrc"


def parser() -> CFSLogParser:
    """Fresh parser with no pod context."""
    return CFSLogParser(pod_name="unknown")


def parser_with_pod(pod_name: str = REAL_POD_NAME) -> CFSLogParser:
    return CFSLogParser(pod_name=pod_name)


# ---------------------------------------------------------------------------
# 1. extract_session_id
# ---------------------------------------------------------------------------

class TestExtractSessionId:
    def test_returns_uuid_from_valid_cfs_pod_name(self):
        result = extract_session_id("cfs-c452edd0-7b87-4af1-b4c4-65d988cc694b-k92xrc")
        assert result == "c452edd0-7b87-4af1-b4c4-65d988cc694b"

    def test_returns_full_string_when_pod_name_does_not_match(self):
        result = extract_session_id("some-random-pod-name")
        assert result == "some-random-pod-name"

    def test_returns_full_string_for_unknown(self):
        result = extract_session_id("unknown")
        assert result == "unknown"


# ---------------------------------------------------------------------------
# 2. PlaybookStart parsing
# ---------------------------------------------------------------------------

class TestPlaybookStartParsing:
    def test_parses_playbook_name_and_repo_url(self):
        p = parser()
        event = p.parse_line(1, "Running foo.yml from repo https://example.com/repo.git")
        assert event is not None
        assert event.event_type == EventType.PLAYBOOK_START
        assert event.playbook == "foo.yml"
        assert event.repo_url == "https://example.com/repo.git"

    def test_carries_line_number(self):
        p = parser()
        event = p.parse_line(42, "Running foo.yml from repo https://example.com/repo.git")
        assert event.line_number == 42

    def test_resets_current_play_and_task_context(self):
        p = parser()
        # Seed some prior state
        p.current_play = "OldPlay"
        p.current_task = "OldTask"
        p.parse_line(1, "Running foo.yml from repo https://example.com/repo.git")
        assert p.current_play is None
        assert p.current_task is None

    def test_accumulates_unique_playbooks(self):
        p = parser()
        p.parse_line(1, "Running foo.yml from repo https://example.com/repo.git")
        p.parse_line(2, "Running bar.yml from repo https://example.com/repo.git")
        # Repeat of foo.yml
        p.parse_line(3, "Running foo.yml from repo https://example.com/repo.git")
        assert p.playbooks == ["foo.yml", "bar.yml"]


# ---------------------------------------------------------------------------
# 3. PlayStart parsing
# ---------------------------------------------------------------------------

class TestPlayStartParsing:
    def test_parses_play_name_with_group_pattern(self):
        p = parser()
        event = p.parse_line(1, "PLAY [Compute:!cfs_image] ***" + "*" * 40)
        assert event is not None
        assert event.event_type == EventType.PLAY_START
        assert event.play_name == "Compute:!cfs_image"

    def test_carries_current_playbook_in_context(self):
        p = parser()
        p.parse_line(1, "Running foo.yml from repo https://example.com/repo.git")
        event = p.parse_line(2, "PLAY [Compute:!cfs_image] ***" + "*" * 40)
        assert event.playbook == "foo.yml"

    def test_resets_task_context_on_new_play(self):
        p = parser()
        p.current_task = "OldTask"
        p.current_role = "OldRole"
        p.parse_line(1, "PLAY [Some Play] ***" + "*" * 40)
        assert p.current_task is None
        assert p.current_role is None


# ---------------------------------------------------------------------------
# 4. TaskStart parsing
# ---------------------------------------------------------------------------

class TestTaskStartParsing:
    def test_parses_task_with_role_prefix(self):
        p = parser()
        event = p.parse_line(1, "TASK [shadow : Change root password in /etc/shadow] ***" + "*" * 20)
        assert event is not None
        assert event.event_type == EventType.TASK_START
        assert event.role == "shadow"
        assert event.task_name == "Change root password in /etc/shadow"

    def test_parses_task_without_role(self):
        p = parser()
        event = p.parse_line(1, "TASK [Compute Node personalization play] ***" + "*" * 20)
        assert event is not None
        assert event.event_type == EventType.TASK_START
        assert event.role is None
        assert event.task_name == "Compute Node personalization play"

    def test_carries_current_play_in_context(self):
        p = parser()
        p.parse_line(1, "PLAY [Compute:!cfs_image] ***" + "*" * 40)
        event = p.parse_line(2, "TASK [shadow : Change root password] ***" + "*" * 20)
        assert event.play_name == "Compute:!cfs_image"


# ---------------------------------------------------------------------------
# 5. TaskResult parsing
# ---------------------------------------------------------------------------

class TestTaskResultParsing:
    def test_ok_result_with_xname(self):
        p = parser()
        event = p.parse_line(1, "ok: [x1301c7s5b0n0]")
        assert event is not None
        assert event.event_type == EventType.TASK_RESULT
        assert event.status == TaskStatus.OK
        assert event.xname == "x1301c7s5b0n0"
        assert event.item is None

    def test_changed_result_with_xname(self):
        p = parser()
        event = p.parse_line(1, "changed: [x1301c7s5b0n0]")
        assert event.status == TaskStatus.CHANGED
        assert event.xname == "x1301c7s5b0n0"

    def test_failed_result_with_xname(self):
        p = parser()
        event = p.parse_line(1, "failed: [x1301c7s5b0n0]")
        assert event.status == TaskStatus.FAILED
        assert event.xname == "x1301c7s5b0n0"

    def test_changed_result_with_item(self):
        p = parser()
        event = p.parse_line(1, "changed: [x1301c7s5b0n0] => (item=subuid)")
        assert event.status == TaskStatus.CHANGED
        assert event.xname == "x1301c7s5b0n0"
        assert event.item == "subuid"

    def test_skipping_no_hosts_matched_is_info(self):
        """'skipping: no hosts matched' has no [xname] brackets, parsed as INFO."""
        p = parser()
        event = p.parse_line(1, "skipping: no hosts matched")
        assert event is not None
        assert event.event_type == EventType.INFO

    def test_delegation_arrow_not_captured_as_xname(self):
        p = parser()
        event = p.parse_line(1, "changed: [x1102c6s1b0n0 -> localhost]")
        assert event is not None
        assert event.event_type == EventType.TASK_RESULT
        # The target "x1102c6s1b0n0 -> localhost" is not a bare xname, so xname is None
        assert event.xname is None

    def test_ok_result_adds_xname_to_session_set(self):
        p = parser()
        p.parse_line(1, "ok: [x1301c7s5b0n0]")
        assert "x1301c7s5b0n0" in p.xnames


# ---------------------------------------------------------------------------
# 6. PlayRecap parsing
# ---------------------------------------------------------------------------

class TestPlayRecapParsing:
    def test_parses_play_recap_line(self):
        p = parser()
        event = p.parse_line(1, "PLAY RECAP *" + "*" * 60)
        assert event is not None
        assert event.event_type == EventType.PLAY_RECAP


# ---------------------------------------------------------------------------
# 7. Warning parsing
# ---------------------------------------------------------------------------

class TestWarningParsing:
    def test_parses_warning_line(self):
        p = parser()
        event = p.parse_line(1, "[WARNING] some warning message here")
        assert event is not None
        assert event.event_type == EventType.WARNING

    def test_ansible_warning_format(self):
        p = parser()
        event = p.parse_line(1, "[WARNING]: Could not match supplied host pattern, ignoring: cfs_image")
        assert event is not None
        assert event.event_type == EventType.WARNING


# ---------------------------------------------------------------------------
# 8. Timestamp extraction
# ---------------------------------------------------------------------------

class TestTimestampExtraction:
    def test_timestamp_line_updates_parser_state(self):
        p = parser()
        result = p.parse_line(1, "Tuesday 07 April 2026  10:45:53 +0000 (0:00:00.634)       0:00:00.634 *")
        # Timestamp-only lines return None (noise)
        assert result is None
        assert p.last_timestamp == datetime(2026, 4, 7, 10, 45, 53, tzinfo=timezone.utc)

    def test_first_timestamp_is_set_only_once(self):
        p = parser()
        p.parse_line(1, "Tuesday 07 April 2026  10:45:53 +0000")
        p.parse_line(2, "Tuesday 07 April 2026  10:46:14 +0000")
        assert p.first_timestamp == datetime(2026, 4, 7, 10, 45, 53, tzinfo=timezone.utc)

    def test_last_seen_timestamp_advances(self):
        p = parser()
        p.parse_line(1, "Tuesday 07 April 2026  10:45:53 +0000")
        p.parse_line(2, "Tuesday 07 April 2026  10:46:14 +0000")
        assert p.last_seen_timestamp == datetime(2026, 4, 7, 10, 46, 14, tzinfo=timezone.utc)

    def test_timestamp_is_attached_to_subsequent_events(self):
        p = parser()
        p.parse_line(1, "Tuesday 07 April 2026  10:45:53 +0000")
        event = p.parse_line(2, "Running foo.yml from repo https://example.com/repo.git")
        assert event.timestamp == datetime(2026, 4, 7, 10, 45, 53, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 9. Xname extraction from subset
# ---------------------------------------------------------------------------

class TestXnameFromSubset:
    def test_extracts_xnames_from_subset_in_failed_to_patch_line(self):
        p = parser()
        line = "Failed to patch on /api/v1/playbooks/369663: {'labels': ['batcher-1dfcf57d-064c-42e0-9f6a-63e4be92c924', 'subset:x1300c7s5b0n0,x1102c7s1b1n0']}"
        p.parse_line(1, line)
        assert "x1300c7s5b0n0" in p.xnames
        assert "x1102c7s1b1n0" in p.xnames

    def test_ignores_non_xname_tokens_in_subset(self):
        p = parser()
        p.parse_line(1, "subset:goodname,x1300c7s5b0n0,notanxname")
        # Only valid xnames are added
        assert "x1300c7s5b0n0" in p.xnames
        assert "notanxname" not in p.xnames


# ---------------------------------------------------------------------------
# 10. Batcher ID extraction
# ---------------------------------------------------------------------------

class TestBatcherIdExtraction:
    def test_extracts_batcher_id_from_failed_to_patch_line(self):
        p = parser()
        line = "Failed to patch on /api/v1: {'labels': ['batcher-1dfcf57d-064c-42e0-9f6a-63e4be92c924']}"
        p.parse_line(1, line)
        assert p.batcher_id == "1dfcf57d-064c-42e0-9f6a-63e4be92c924"

    def test_batcher_id_is_set_only_once(self):
        p = parser()
        p.parse_line(1, "batcher-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee first")
        p.parse_line(2, "batcher-11111111-2222-3333-4444-555555555555 second")
        assert p.batcher_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ---------------------------------------------------------------------------
# 11. Noise filtering
# ---------------------------------------------------------------------------

class TestNoiseFiltering:
    def test_empty_line_returns_none(self):
        p = parser()
        assert p.parse_line(1, "") is None

    def test_whitespace_only_line_returns_none(self):
        p = parser()
        assert p.parse_line(1, "   \n") is None

    def test_failed_to_patch_line_returns_none(self):
        p = parser()
        result = p.parse_line(1, "Failed to patch on /api/v1/playbooks/123: {}")
        assert result is None

    def test_curl_progress_line_returns_none(self):
        p = parser()
        result = p.parse_line(1, "  % Total    % Received % Xferd  Average Speed")
        assert result is None

    def test_http_header_line_returns_none(self):
        p = parser()
        assert p.parse_line(1, "HTTP/1.1 200 OK") is None

    def test_separator_tilde_line_returns_none(self):
        p = parser()
        assert p.parse_line(1, "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~") is None

    def test_separator_equals_line_returns_none(self):
        p = parser()
        assert p.parse_line(1, "===============================================================================") is None

    def test_playbook_run_took_line_returns_none(self):
        p = parser()
        assert p.parse_line(1, "Playbook run took 0 days, 0 hours, 0 minutes, 0 seconds") is None

    def test_timestamp_only_line_returns_none(self):
        p = parser()
        assert p.parse_line(1, "Tuesday 07 April 2026  10:45:53 +0000 (0:00:00.634)") is None


# ---------------------------------------------------------------------------
# 12. Stateful context tracking
# ---------------------------------------------------------------------------

class TestStatefulContextTracking:
    def test_task_start_carries_current_playbook_name(self):
        p = parser()
        p.parse_line(1, "Running my_play.yml from repo https://example.com/repo.git")
        p.parse_line(2, "PLAY [Compute] ***" + "*" * 50)
        event = p.parse_line(3, "TASK [shadow : do something] ***" + "*" * 40)
        assert event.playbook == "my_play.yml"
        assert event.play_name == "Compute"

    def test_task_result_carries_current_task_name(self):
        p = parser()
        p.parse_line(1, "TASK [shadow : Change root password] ***" + "*" * 30)
        event = p.parse_line(2, "ok: [x1301c7s5b0n0]")
        assert event.task_name == "Change root password"
        assert event.role == "shadow"

    def test_second_playbook_replaces_context(self):
        p = parser()
        p.parse_line(1, "Running first.yml from repo https://example.com/repo.git")
        p.parse_line(2, "Running second.yml from repo https://example.com/repo.git")
        event = p.parse_line(3, "TASK [some : task] ***" + "*" * 40)
        assert event.playbook == "second.yml"


# ---------------------------------------------------------------------------
# 13. get_session_info
# ---------------------------------------------------------------------------

class TestGetSessionInfo:
    def test_session_info_contains_accumulated_xnames(self):
        p = parser()
        p.parse_line(1, "ok: [x1301c7s5b0n0]")
        p.parse_line(2, "ok: [x1102c6s1b0n0]")
        info = p.get_session_info()
        assert "x1301c7s5b0n0" in info.xnames
        assert "x1102c6s1b0n0" in info.xnames

    def test_session_info_xnames_are_sorted(self):
        p = parser()
        p.parse_line(1, "ok: [x1301c7s5b0n0]")
        p.parse_line(2, "ok: [x1102c6s1b0n0]")
        info = p.get_session_info()
        assert info.xnames == sorted(info.xnames)

    def test_session_info_contains_accumulated_playbooks(self):
        p = parser()
        p.parse_line(1, "Running alpha.yml from repo https://example.com/r.git")
        p.parse_line(2, "Running beta.yml from repo https://example.com/r.git")
        info = p.get_session_info()
        assert info.playbooks == ["alpha.yml", "beta.yml"]

    def test_session_info_started_at_and_ended_at(self):
        p = parser()
        p.parse_line(1, "Tuesday 07 April 2026  10:45:53 +0000")
        p.parse_line(2, "Tuesday 07 April 2026  10:58:33 +0000")
        info = p.get_session_info()
        assert info.started_at == datetime(2026, 4, 7, 10, 45, 53, tzinfo=timezone.utc)
        assert info.ended_at == datetime(2026, 4, 7, 10, 58, 33, tzinfo=timezone.utc)

    def test_session_info_batcher_id(self):
        p = parser()
        p.parse_line(1, "batcher-1dfcf57d-064c-42e0-9f6a-63e4be92c924 info")
        info = p.get_session_info()
        assert info.batcher_id == "1dfcf57d-064c-42e0-9f6a-63e4be92c924"

    def test_session_info_pod_name_and_session_id(self):
        p = parser_with_pod()
        info = p.get_session_info()
        assert info.pod_name == REAL_POD_NAME
        assert info.session_id == "c452edd0-7b87-4af1-b4c4-65d988cc694b"


# ---------------------------------------------------------------------------
# 14. parse_file against real sample
# ---------------------------------------------------------------------------

class TestParseFile:
    @pytest.fixture(scope="class")
    def parsed(self):
        p = parser_with_pod()
        session, events = p.parse_file(SAMPLE_LOG)
        return session, events

    def test_session_id_extracted_correctly(self, parsed):
        session, _ = parsed
        assert session.session_id == "c452edd0-7b87-4af1-b4c4-65d988cc694b"

    def test_finds_25_unique_xnames(self, parsed):
        session, _ = parsed
        assert len(session.xnames) == 25

    def test_finds_4_playbooks(self, parsed):
        session, _ = parsed
        assert len(session.playbooks) == 4

    def test_playbook_names_are_correct(self, parsed):
        session, _ = parsed
        assert session.playbooks == [
            "csm_packages.yml",
            "gpu_customize_driver_playbook.yml",
            "shs_cassini_install.yml",
            "cos-compute.yml",
        ]

    def test_batcher_id_is_correct(self, parsed):
        session, _ = parsed
        assert session.batcher_id == "1dfcf57d-064c-42e0-9f6a-63e4be92c924"

    def test_started_at_timestamp(self, parsed):
        session, _ = parsed
        assert session.started_at == datetime(2026, 4, 7, 10, 45, 53, tzinfo=timezone.utc)

    def test_ended_at_timestamp(self, parsed):
        session, _ = parsed
        assert session.ended_at == datetime(2026, 4, 7, 10, 58, 33, tzinfo=timezone.utc)

    def test_events_list_is_non_empty(self, parsed):
        _, events = parsed
        assert len(events) > 0

    def test_playbook_start_events_count(self, parsed):
        _, events = parsed
        pb_events = [e for e in events if e.event_type == EventType.PLAYBOOK_START]
        assert len(pb_events) == 4

    def test_task_result_events_present(self, parsed):
        _, events = parsed
        result_events = [e for e in events if e.event_type == EventType.TASK_RESULT]
        assert len(result_events) > 0

    def test_no_none_events_in_list(self, parsed):
        _, events = parsed
        assert all(e is not None for e in events)


# ---------------------------------------------------------------------------
# 15. LogEvent.to_dict serialization
# ---------------------------------------------------------------------------

class TestLogEventToDict:
    def test_required_fields_always_present(self):
        event = LogEvent(
            event_type=EventType.INFO,
            line_number=5,
            raw_line="some info line",
        )
        d = event.to_dict()
        assert d["event_type"] == "info"
        assert d["line_number"] == 5
        assert d["raw_line"] == "some info line"

    def test_optional_fields_omitted_when_none(self):
        event = LogEvent(
            event_type=EventType.INFO,
            line_number=1,
            raw_line="line",
        )
        d = event.to_dict()
        assert "timestamp" not in d
        assert "playbook" not in d
        assert "xname" not in d
        assert "item" not in d

    def test_timestamp_serialized_as_iso_string(self):
        ts = datetime(2026, 4, 7, 10, 45, 53, tzinfo=timezone.utc)
        event = LogEvent(
            event_type=EventType.TASK_RESULT,
            line_number=10,
            raw_line="ok: [x1301c7s5b0n0]",
            timestamp=ts,
            status=TaskStatus.OK,
            xname="x1301c7s5b0n0",
        )
        d = event.to_dict()
        assert d["timestamp"] == "2026-04-07T10:45:53+00:00"

    def test_status_serialized_as_string_value(self):
        event = LogEvent(
            event_type=EventType.TASK_RESULT,
            line_number=1,
            raw_line="failed: [x1301c7s5b0n0]",
            status=TaskStatus.FAILED,
        )
        d = event.to_dict()
        assert d["status"] == "failed"

    def test_all_optional_fields_present_when_set(self):
        ts = datetime(2026, 4, 7, 10, 45, 53, tzinfo=timezone.utc)
        event = LogEvent(
            event_type=EventType.TASK_RESULT,
            line_number=99,
            raw_line="changed: [x1301c7s5b0n0] => (item=subuid)",
            timestamp=ts,
            playbook="foo.yml",
            repo_url="https://example.com/repo.git",
            play_name="Compute",
            role="shadow",
            task_name="Change root password",
            status=TaskStatus.CHANGED,
            xname="x1301c7s5b0n0",
            item="subuid",
        )
        d = event.to_dict()
        assert d["playbook"] == "foo.yml"
        assert d["repo_url"] == "https://example.com/repo.git"
        assert d["play_name"] == "Compute"
        assert d["role"] == "shadow"
        assert d["task_name"] == "Change root password"
        assert d["xname"] == "x1301c7s5b0n0"
        assert d["item"] == "subuid"
