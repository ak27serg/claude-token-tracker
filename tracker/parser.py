"""
Parse Claude Code JSONL session transcripts and yield Turn records.

Each JSONL file lives at:
  ~/.claude/projects/<encoded-path>/<session-id>.jsonl

Claude Code writes multiple assistant records per API call (streaming
pre-response + final). We deduplicate on `message.id` keeping the record
with the highest output_tokens (the final, complete one).
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class Turn:
    message_id: str          # Anthropic API message ID (msg_xxx)
    outer_uuid: str          # JSONL record UUID
    session_id: str
    project_path: str        # actual cwd (e.g. /Users/foo/myproject)
    timestamp: str           # ISO-8601
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int


def _get_cwd_from_jsonl(path: str) -> str:
    """Read the first user-type record to get the working directory."""
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    obj = json.loads(raw)
                    if obj.get("type") == "user":
                        return obj.get("cwd", "")
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return ""


def iter_turns(jsonl_path: str, project_path: str) -> Iterator[Turn]:
    """
    Parse one JSONL file and yield de-duplicated Turn records.
    Only records with at least some token usage are included.
    """
    # message_id -> best Turn seen so far
    best: dict[str, Turn] = {}

    try:
        with open(jsonl_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if obj.get("type") != "assistant":
            continue

        msg = obj.get("message", {})
        usage = msg.get("usage")
        if not usage:
            continue

        input_tok = usage.get("input_tokens", 0)
        output_tok = usage.get("output_tokens", 0)
        cache_create = usage.get("cache_creation_input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)

        # Skip entirely empty records
        total = input_tok + output_tok + cache_create + cache_read
        if total == 0:
            continue

        message_id = msg.get("id") or obj.get("uuid", "")
        outer_uuid = obj.get("uuid", "")
        session_id = obj.get("sessionId", "")
        timestamp = obj.get("timestamp", "")
        model = msg.get("model", "unknown")

        turn = Turn(
            message_id=message_id,
            outer_uuid=outer_uuid,
            session_id=session_id,
            project_path=project_path,
            timestamp=timestamp,
            model=model,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cache_creation_tokens=cache_create,
            cache_read_tokens=cache_read,
        )

        existing = best.get(message_id)
        if existing is None or output_tok > existing.output_tokens:
            best[message_id] = turn

    yield from best.values()


def scan_projects(projects_dir: Optional[str] = None) -> Iterator[tuple[str, list[str]]]:
    """
    Yield (project_path, [jsonl_file_paths]) for every Claude Code project.
    project_path is the real filesystem path (from the JSONL cwd field).
    """
    if projects_dir is None:
        projects_dir = os.path.expanduser("~/.claude/projects")

    if not os.path.isdir(projects_dir):
        return

    for entry in os.scandir(projects_dir):
        if not entry.is_dir():
            continue
        jsonl_files = glob.glob(os.path.join(entry.path, "*.jsonl"))
        if not jsonl_files:
            continue

        # Derive the real cwd from the first available JSONL in this project
        project_path = _get_cwd_from_jsonl(jsonl_files[0]) or entry.name
        yield project_path, jsonl_files


def scan_all_turns(projects_dir: Optional[str] = None) -> Iterator[Turn]:
    """Yield every Turn across all projects."""
    for project_path, jsonl_files in scan_projects(projects_dir):
        for jsonl_path in jsonl_files:
            yield from iter_turns(jsonl_path, project_path)


def scan_session_turns(session_jsonl_path: str) -> Iterator[Turn]:
    """Yield turns for a single JSONL file (used by the hook ingest)."""
    project_path = _get_cwd_from_jsonl(session_jsonl_path)
    yield from iter_turns(session_jsonl_path, project_path)
