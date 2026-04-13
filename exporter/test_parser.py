"""Tests for CFSLogParser failure detection from PLAY RECAP."""

from parser import CFSLogParser


def test_has_failures_false_when_no_recap():
    p = CFSLogParser(pod_name="cfs-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-xyz")
    p.parse_line(1, "TASK [some_role : do_thing] ***")
    p.parse_line(2, "ok: [x3000c0s1b0n0]")
    assert p.has_failures is False


def test_has_failures_false_when_all_ok():
    p = CFSLogParser(pod_name="cfs-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-xyz")
    p.parse_line(1, "PLAY RECAP *************")
    p.parse_line(2, "x3000c0s1b0n0      : ok=10   changed=2    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0")
    assert p.has_failures is False


def test_has_failures_true_when_failed():
    p = CFSLogParser(pod_name="cfs-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-xyz")
    p.parse_line(1, "PLAY RECAP *************")
    p.parse_line(2, "x3000c0s1b0n0      : ok=10   changed=2    unreachable=0    failed=3    skipped=5    rescued=0    ignored=0")
    assert p.has_failures is True


def test_has_failures_true_when_unreachable():
    p = CFSLogParser(pod_name="cfs-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-xyz")
    p.parse_line(1, "PLAY RECAP *************")
    p.parse_line(2, "x3000c0s1b0n0      : ok=0    changed=0    unreachable=1    failed=0    skipped=0    rescued=0    ignored=0")
    assert p.has_failures is True


def test_has_failures_true_with_multiple_hosts_mixed():
    p = CFSLogParser(pod_name="cfs-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-xyz")
    p.parse_line(1, "PLAY RECAP *************")
    p.parse_line(2, "x3000c0s1b0n0      : ok=10   changed=2    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0")
    p.parse_line(3, "x3000c0s1b0n1      : ok=8    changed=1    unreachable=0    failed=1    skipped=5    rescued=0    ignored=0")
    assert p.has_failures is True


def test_has_failures_persists_across_multiple_recaps():
    """If one playbook fails but a later one succeeds, has_failures stays True."""
    p = CFSLogParser(pod_name="cfs-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-xyz")
    # First playbook — fails
    p.parse_line(1, "PLAY RECAP *************")
    p.parse_line(2, "x3000c0s1b0n0      : ok=5    changed=0    unreachable=0    failed=2    skipped=0    rescued=0    ignored=0")
    # Second playbook — succeeds
    p.parse_line(3, "Running site.yml from repo https://example.com/repo.git")
    p.parse_line(4, "PLAY RECAP *************")
    p.parse_line(5, "x3000c0s1b0n0      : ok=10   changed=2    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0")
    assert p.has_failures is True
