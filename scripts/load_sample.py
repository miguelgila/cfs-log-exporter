#!/usr/bin/env python3
"""
Load a sample CFS log file into the receiver API.
Usage: python scripts/load_sample.py [log_file] [receiver_url]
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "exporter"))

import httpx
from parser import CFSLogParser

LOG_FILE = sys.argv[1] if len(sys.argv) > 1 else "cfs-log.txt"
RECEIVER_URL = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
API_KEY = os.environ.get("API_KEY", "changeme")
POD_NAME = sys.argv[3] if len(sys.argv) > 3 else "cfs-c452edd0-7b87-4af1-b4c4-65d988cc694b-k92xrc"

BATCH_SIZE = 200


def main():
    parser = CFSLogParser(pod_name=POD_NAME)
    session_info, events = parser.parse_file(LOG_FILE)

    print(f"Parsed {len(events)} events from {LOG_FILE}")
    print(f"Session: {session_info.session_id}")
    print(f"Xnames: {len(session_info.xnames)}")
    print(f"Playbooks: {session_info.playbooks}")

    client = httpx.Client(timeout=30)

    # Send in batches
    for i in range(0, len(events), BATCH_SIZE):
        batch = events[i : i + BATCH_SIZE]
        is_last = (i + BATCH_SIZE) >= len(events)

        payload = {
            "session": {
                "session_uuid": session_info.session_id,
                "pod_name": session_info.pod_name,
                "batcher_id": session_info.batcher_id,
                "xnames": session_info.xnames,
                "playbooks": session_info.playbooks,
                "started_at": session_info.started_at.isoformat() if session_info.started_at else None,
                "ended_at": session_info.ended_at.isoformat() if is_last and session_info.ended_at else None,
                "status": "completed" if is_last else "running",
            },
            "events": [e.to_dict() for e in batch],
        }

        resp = client.post(
            f"{RECEIVER_URL}/api/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

        if resp.status_code != 200:
            print(f"Error: {resp.status_code} {resp.text}")
            sys.exit(1)

        result = resp.json()
        print(f"  Batch {i // BATCH_SIZE + 1}: {result['lines_inserted']} lines inserted")

    print(f"\nDone! View at {RECEIVER_URL}")


if __name__ == "__main__":
    main()
