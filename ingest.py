#!/usr/bin/env python3
"""
Ingest script — called by the Claude Code Stop hook after each session turn.

Claude Code pipes a JSON payload to stdin:
  {
    "session_id": "...",
    "transcript_path": "/path/to/session.jsonl",   # may be absent
    "stop_hook_active": true,
    ...
  }

We rescan the relevant JSONL (or all projects) and update the DB.
"""

from __future__ import annotations

import json
import sys
import os
import glob

# Allow running from any directory
sys.path.insert(0, os.path.dirname(__file__))

from tracker.parser import scan_all_turns, scan_session_turns
from tracker.db import init_db, upsert_turns_bulk


def main() -> None:
    init_db()

    payload: dict = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            payload = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        pass

    transcript_path: str | None = payload.get("transcript_path")
    session_id: str | None = payload.get("session_id")

    if transcript_path and os.path.isfile(transcript_path):
        # Fast path: only rescan the one file that just changed
        turns = list(scan_session_turns(transcript_path))
    elif session_id:
        # Search for the JSONL file by session ID
        projects_dir = os.path.expanduser("~/.claude/projects")
        pattern = os.path.join(projects_dir, "**", f"{session_id}.jsonl")
        matches = glob.glob(pattern, recursive=True)
        if matches:
            turns = list(scan_session_turns(matches[0]))
        else:
            turns = list(scan_all_turns())
    else:
        # Full rescan (first run or unknown session)
        turns = list(scan_all_turns())

    count = upsert_turns_bulk(turns)
    # Write to stderr so Claude Code doesn't see it as output
    print(f"[token-tracker] ingested {count} turns", file=sys.stderr)


if __name__ == "__main__":
    main()
