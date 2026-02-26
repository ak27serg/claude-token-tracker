"""
SQLite persistence layer for the token tracker.

DB location: ~/.claude/token_tracker.db
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

from .parser import Turn
from .pricing import calculate_cost

DB_PATH = os.path.expanduser("~/.claude/token_tracker.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    message_id            TEXT PRIMARY KEY,
    session_id            TEXT NOT NULL,
    timestamp             TEXT NOT NULL,
    model                 TEXT NOT NULL,
    input_tokens          INTEGER NOT NULL DEFAULT 0,
    output_tokens         INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
    cost_usd              REAL    NOT NULL DEFAULT 0.0,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_turns_session   ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp);
"""


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(_SCHEMA)


def upsert_turns_bulk(turns: list[Turn]) -> int:
    """Idempotent bulk upsert. Returns number of turns processed."""
    count = 0
    with _conn() as con:
        for turn in turns:
            cost = calculate_cost(
                turn.model,
                turn.input_tokens,
                turn.output_tokens,
                turn.cache_creation_tokens,
                turn.cache_read_tokens,
            )
            con.execute(
                """
                INSERT INTO sessions (session_id, project_path, first_seen, last_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_seen = MAX(last_seen, excluded.last_seen)
                """,
                (turn.session_id, turn.project_path, turn.timestamp, turn.timestamp),
            )
            con.execute(
                """
                INSERT INTO turns
                    (message_id, session_id, timestamp, model,
                     input_tokens, output_tokens, cache_creation_tokens,
                     cache_read_tokens, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    output_tokens         = MAX(output_tokens, excluded.output_tokens),
                    cache_creation_tokens = MAX(cache_creation_tokens, excluded.cache_creation_tokens),
                    cache_read_tokens     = MAX(cache_read_tokens, excluded.cache_read_tokens),
                    cost_usd              = MAX(cost_usd, excluded.cost_usd)
                """,
                (
                    turn.message_id,
                    turn.session_id,
                    turn.timestamp,
                    turn.model,
                    turn.input_tokens,
                    turn.output_tokens,
                    turn.cache_creation_tokens,
                    turn.cache_read_tokens,
                    cost,
                ),
            )
            count += 1
    return count


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def query_totals() -> dict:
    """All-time aggregate stats."""
    with _conn() as con:
        row = con.execute(
            """
            SELECT
                COUNT(DISTINCT session_id) AS sessions,
                COUNT(*)                   AS turns,
                SUM(input_tokens)          AS input_tokens,
                SUM(output_tokens)         AS output_tokens,
                SUM(cache_creation_tokens) AS cache_creation_tokens,
                SUM(cache_read_tokens)     AS cache_read_tokens,
                SUM(cost_usd)              AS cost_usd
            FROM turns
            """
        ).fetchone()
        return dict(row) if row else {}


def query_today() -> dict:
    """Stats for the current calendar day (UTC)."""
    with _conn() as con:
        row = con.execute(
            """
            SELECT
                COUNT(DISTINCT session_id) AS sessions,
                COUNT(*)                   AS turns,
                SUM(input_tokens)          AS input_tokens,
                SUM(output_tokens)         AS output_tokens,
                SUM(cache_creation_tokens) AS cache_creation_tokens,
                SUM(cache_read_tokens)     AS cache_read_tokens,
                SUM(cost_usd)              AS cost_usd
            FROM turns
            WHERE DATE(timestamp) = DATE('now')
            """
        ).fetchone()
        return dict(row) if row else {}


def query_sessions(limit: int = 200) -> list[dict]:
    """Sessions ordered by most recent activity."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                s.session_id,
                s.project_path,
                s.first_seen,
                s.last_seen,
                COUNT(t.message_id)            AS turns,
                SUM(t.input_tokens)            AS input_tokens,
                SUM(t.output_tokens)           AS output_tokens,
                SUM(t.cache_creation_tokens)   AS cache_creation_tokens,
                SUM(t.cache_read_tokens)       AS cache_read_tokens,
                SUM(t.cost_usd)                AS cost_usd,
                MAX(t.model)                   AS model
            FROM sessions s
            JOIN turns t ON t.session_id = s.session_id
            GROUP BY s.session_id
            ORDER BY s.last_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def query_session_turns(session_id: str) -> list[dict]:
    """All turns for a specific session, oldest first."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT *
            FROM turns
            WHERE session_id = ?
            ORDER BY timestamp ASC
            """,
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def query_projects() -> list[dict]:
    """Aggregate by project path, ordered by total cost."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                s.project_path,
                COUNT(DISTINCT s.session_id)   AS sessions,
                COUNT(t.message_id)            AS turns,
                SUM(t.input_tokens)            AS input_tokens,
                SUM(t.output_tokens)           AS output_tokens,
                SUM(t.cache_creation_tokens)   AS cache_creation_tokens,
                SUM(t.cache_read_tokens)       AS cache_read_tokens,
                SUM(t.cost_usd)                AS cost_usd
            FROM sessions s
            JOIN turns t ON t.session_id = s.session_id
            GROUP BY s.project_path
            ORDER BY cost_usd DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def query_models() -> list[dict]:
    """Aggregate by model, ordered by total cost."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                model,
                COUNT(*)                   AS turns,
                SUM(input_tokens)          AS input_tokens,
                SUM(output_tokens)         AS output_tokens,
                SUM(cache_creation_tokens) AS cache_creation_tokens,
                SUM(cache_read_tokens)     AS cache_read_tokens,
                SUM(cost_usd)              AS cost_usd
            FROM turns
            GROUP BY model
            ORDER BY cost_usd DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def query_rolling_window(hours: int = 5) -> dict:
    """Token usage in the last N hours (rolling window for rate limiting)."""
    with _conn() as con:
        row = con.execute(
            """
            SELECT
                COUNT(DISTINCT session_id) AS sessions,
                COUNT(*)                   AS turns,
                SUM(input_tokens)          AS input_tokens,
                SUM(output_tokens)         AS output_tokens,
                SUM(cache_creation_tokens) AS cache_creation_tokens,
                SUM(cache_read_tokens)     AS cache_read_tokens,
                SUM(cost_usd)              AS cost_usd,
                MIN(timestamp)             AS oldest_turn
            FROM turns
            WHERE timestamp >= datetime('now', ?)
            """,
            (f"-{hours} hours",),
        ).fetchone()
        return dict(row) if row else {}


def query_daily(days: int = 30) -> list[dict]:
    """Daily aggregates for the last N days."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                DATE(timestamp)            AS day,
                COUNT(DISTINCT session_id) AS sessions,
                COUNT(*)                   AS turns,
                SUM(input_tokens)          AS input_tokens,
                SUM(output_tokens)         AS output_tokens,
                SUM(cache_creation_tokens) AS cache_creation_tokens,
                SUM(cache_read_tokens)     AS cache_read_tokens,
                SUM(cost_usd)              AS cost_usd
            FROM turns
            WHERE DATE(timestamp) >= DATE('now', ?)
            GROUP BY DATE(timestamp)
            ORDER BY day ASC
            """,
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]
