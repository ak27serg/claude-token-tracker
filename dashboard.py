#!/usr/bin/env python3
"""
Interactive token-usage dashboard for Claude Code.

Usage:
    python3 dashboard.py          # open dashboard
    python3 dashboard.py --ingest # rescan all projects first, then open

Keyboard shortcuts:
    r / F5   Refresh data
    q / Q    Quit
    ↑ ↓      Navigate tables
    Enter    Drill into a session (on Sessions tab)
    Esc      Back to session list
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# Allow running from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tracker.db import (
    init_db,
    query_daily,
    query_models,
    query_projects,
    query_rolling_window,
    query_sessions,
    query_session_turns,
    query_today,
    query_totals,
    upsert_turns_bulk,
)
from tracker.parser import scan_all_turns
from tracker.config import (
    PLAN_LIMITS,
    PLAN_NAMES,
    PLANS,
    cycle_plan,
    get_limit,
    get_plan,
    set_plan,
)

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_tokens(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _fmt_cost(usd: float | None) -> str:
    if usd is None:
        return "—"
    if usd >= 1:
        return f"${usd:.2f}"
    return f"${usd:.4f}"


def _fmt_ts(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16]


def _short_path(path: str, max_len: int = 40) -> str:
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]
    if len(path) > max_len:
        return "…" + path[-(max_len - 1):]
    return path


def _sparkline(daily: list[dict], width: int = 50) -> str:
    """ASCII bar chart for daily token usage."""
    if not daily:
        return "  No data yet."

    bars = "▁▂▃▄▅▆▇█"
    totals = [
        (d["day"], (d["input_tokens"] or 0) + (d["output_tokens"] or 0) +
         (d["cache_creation_tokens"] or 0) + (d["cache_read_tokens"] or 0))
        for d in daily
    ]
    max_val = max(t for _, t in totals) or 1

    lines = []
    lines.append("  Daily token usage (last 30 days)\n")
    lines.append("  " + "─" * (width + 2))

    for day, total in totals:
        ratio = total / max_val
        filled = int(ratio * width)
        bar = "█" * filled + "░" * (width - filled)
        lines.append(f"  {day}  [{bar}]  {_fmt_tokens(total)}")

    lines.append("  " + "─" * (width + 2))
    lines.append(f"\n  Peak day: {_fmt_tokens(max_val)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stats banner
# ---------------------------------------------------------------------------

class StatsBanner(Static):
    """Single-line summary of all-time and today's stats."""

    DEFAULT_CSS = """
    StatsBanner {
        height: 3;
        padding: 1 2;
        background: $panel;
        color: $text;
        border-bottom: solid $primary;
    }
    """

    def update_stats(self, totals: dict, today: dict) -> None:
        def total_tok(d: dict) -> int:
            return (
                (d.get("input_tokens") or 0)
                + (d.get("output_tokens") or 0)
                + (d.get("cache_creation_tokens") or 0)
                + (d.get("cache_read_tokens") or 0)
            )

        all_tok = total_tok(totals)
        all_cost = totals.get("cost_usd") or 0.0
        all_sessions = totals.get("sessions") or 0
        all_turns = totals.get("turns") or 0

        today_tok = total_tok(today)
        today_cost = today.get("cost_usd") or 0.0
        today_sessions = today.get("sessions") or 0

        text = (
            f"[bold]All-time:[/bold] {_fmt_tokens(all_tok)} tokens | "
            f"{_fmt_cost(all_cost)} | "
            f"{all_sessions} sessions | {all_turns} turns"
            f"    [bold]Today:[/bold] {_fmt_tokens(today_tok)} tokens | "
            f"{_fmt_cost(today_cost)} | {today_sessions} sessions"
        )
        self.update(text)


# ---------------------------------------------------------------------------
# Rate-limit progress bar
# ---------------------------------------------------------------------------

class RateLimitBar(Static):
    """Shows token usage relative to the plan's 5-hour rolling window limit."""

    DEFAULT_CSS = """
    RateLimitBar {
        padding: 1 2;
        background: $panel;
        color: $text;
        border-bottom: solid $accent;
    }
    """

    def update_bar(self, window: dict, plan: str, limit: int) -> None:
        output_tokens = window.get("output_tokens") or 0
        pct = min(output_tokens / limit, 1.0) if limit else 0
        pct_display = pct * 100

        # Color based on usage
        if pct < 0.60:
            color = "green"
        elif pct < 0.85:
            color = "yellow"
        else:
            color = "red"

        # Progress bar (30 chars wide)
        bar_width = 30
        filled = int(pct * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Estimate when the window resets
        oldest = window.get("oldest_turn")
        reset_text = ""
        if oldest and output_tokens > 0:
            try:
                oldest_dt = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
                # The oldest turn falls off after 5 hours
                reset_at = oldest_dt + timedelta(hours=5)
                now = datetime.now(timezone.utc)
                remaining = reset_at - now
                if remaining.total_seconds() > 0:
                    hrs, rem = divmod(int(remaining.total_seconds()), 3600)
                    mins = rem // 60
                    reset_text = f" · resets in ~{hrs}h{mins:02d}m"
            except (ValueError, TypeError):
                pass

        plan_name = PLAN_NAMES.get(plan, plan)
        text = (
            f"[bold]Rate limit[/bold] \\[{plan_name}]  "
            f"[{color}]{bar}[/{color}]  "
            f"{_fmt_tokens(output_tokens)} / {_fmt_tokens(limit)} output tokens "
            f"({pct_display:.0f}%){reset_text}"
            f"    [dim]P to switch plan[/dim]"
        )
        self.update(text)


# ---------------------------------------------------------------------------
# Sessions tab
# ---------------------------------------------------------------------------

class SessionsTable(DataTable):
    """Sortable table of all sessions."""

    COLUMNS = [
        ("Last Active",    "last_seen"),
        ("Project",        "project_path"),
        ("Model",          "model"),
        ("Turns",          "turns"),
        ("Input",          "input_tokens"),
        ("Output",         "output_tokens"),
        ("Cache-R",        "cache_read_tokens"),
        ("Cache-W",        "cache_creation_tokens"),
        ("Cost",           "cost_usd"),
    ]

    def on_mount(self) -> None:
        self.cursor_type = "row"
        for label, _ in self.COLUMNS:
            self.add_column(label)

    def populate(self, sessions: list[dict]) -> None:
        self.clear()
        for s in sessions:
            self.add_row(
                _fmt_ts(s.get("last_seen")),
                _short_path(s.get("project_path", "?")),
                s.get("model", "?"),
                str(s.get("turns") or 0),
                _fmt_tokens(s.get("input_tokens")),
                _fmt_tokens(s.get("output_tokens")),
                _fmt_tokens(s.get("cache_read_tokens")),
                _fmt_tokens(s.get("cache_creation_tokens")),
                _fmt_cost(s.get("cost_usd")),
                key=s["session_id"],
            )


# ---------------------------------------------------------------------------
# Session detail panel
# ---------------------------------------------------------------------------

class SessionDetail(Static):
    """Shows per-turn breakdown for the selected session."""

    DEFAULT_CSS = """
    SessionDetail {
        height: 14;
        padding: 1 2;
        background: $surface;
        border-top: solid $primary;
        overflow-y: auto;
    }
    """

    def show_session(self, session_id: str, project_path: str) -> None:
        turns = query_session_turns(session_id)
        if not turns:
            self.update(f"  [dim]No turns found for session {session_id}[/dim]")
            return

        header = f"[bold]{_short_path(project_path)}[/bold]  ·  {len(turns)} turns  ·  session {session_id[:8]}…\n"
        col_w = [22, 10, 10, 10, 10, 10, 8]
        headers = ["Timestamp", "Input", "Output", "Cache-R", "Cache-W", "Total", "Cost"]
        sep = "  " + "  ".join("─" * w for w in col_w)
        hdr_line = "  " + "  ".join(h.ljust(w) for h, w in zip(headers, col_w))

        rows = [header, hdr_line, sep]
        total_cost = 0.0
        for t in turns:
            total = (
                (t.get("input_tokens") or 0)
                + (t.get("output_tokens") or 0)
                + (t.get("cache_creation_tokens") or 0)
                + (t.get("cache_read_tokens") or 0)
            )
            cost = t.get("cost_usd") or 0.0
            total_cost += cost
            cells = [
                _fmt_ts(t.get("timestamp")).ljust(col_w[0]),
                _fmt_tokens(t.get("input_tokens")).ljust(col_w[1]),
                _fmt_tokens(t.get("output_tokens")).ljust(col_w[2]),
                _fmt_tokens(t.get("cache_read_tokens")).ljust(col_w[3]),
                _fmt_tokens(t.get("cache_creation_tokens")).ljust(col_w[4]),
                _fmt_tokens(total).ljust(col_w[5]),
                _fmt_cost(cost).ljust(col_w[6]),
            ]
            rows.append("  " + "  ".join(cells))

        rows.append(sep)
        rows.append(f"  [bold]Total cost: {_fmt_cost(total_cost)}[/bold]")
        self.update("\n".join(rows))

    def clear_detail(self) -> None:
        self.update("  [dim]Select a session above to see per-turn details.[/dim]")


# ---------------------------------------------------------------------------
# Projects tab
# ---------------------------------------------------------------------------

class ProjectsTable(DataTable):
    def on_mount(self) -> None:
        self.cursor_type = "row"
        for col in ["Project", "Sessions", "Turns", "Input", "Output", "Cache-R", "Cache-W", "Cost"]:
            self.add_column(col)

    def populate(self, projects: list[dict]) -> None:
        self.clear()
        for p in projects:
            self.add_row(
                _short_path(p.get("project_path", "?"), 50),
                str(p.get("sessions") or 0),
                str(p.get("turns") or 0),
                _fmt_tokens(p.get("input_tokens")),
                _fmt_tokens(p.get("output_tokens")),
                _fmt_tokens(p.get("cache_read_tokens")),
                _fmt_tokens(p.get("cache_creation_tokens")),
                _fmt_cost(p.get("cost_usd")),
            )


# ---------------------------------------------------------------------------
# Models tab
# ---------------------------------------------------------------------------

class ModelsTable(DataTable):
    def on_mount(self) -> None:
        self.cursor_type = "row"
        for col in ["Model", "Turns", "Input", "Output", "Cache-R", "Cache-W", "Cost"]:
            self.add_column(col)

    def populate(self, models: list[dict]) -> None:
        self.clear()
        for m in models:
            self.add_row(
                m.get("model", "?"),
                str(m.get("turns") or 0),
                _fmt_tokens(m.get("input_tokens")),
                _fmt_tokens(m.get("output_tokens")),
                _fmt_tokens(m.get("cache_read_tokens")),
                _fmt_tokens(m.get("cache_creation_tokens")),
                _fmt_cost(m.get("cost_usd")),
            )


# ---------------------------------------------------------------------------
# Daily tab
# ---------------------------------------------------------------------------

class DailyChart(Static):
    DEFAULT_CSS = """
    DailyChart {
        padding: 1 2;
        overflow-y: auto;
    }
    """

    def populate(self, daily: list[dict]) -> None:
        self.update(_sparkline(daily))


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class TokenTrackerApp(App):
    """Claude Code Token Usage Tracker"""

    CSS = """
    Screen {
        background: $surface;
        layout: vertical;
    }
    #stats-banner {
        height: auto;
        min-height: 3;
    }
    #rate-limit-bar {
        height: auto;
        min-height: 3;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    SessionsTable {
        height: 1fr;
    }
    ProjectsTable {
        height: 1fr;
    }
    ModelsTable {
        height: 1fr;
    }
    #sessions-pane {
        height: 1fr;
        layout: vertical;
    }
    """

    BINDINGS = [
        Binding("r,f5", "refresh", "Refresh"),
        Binding("p", "cycle_plan", "Switch plan"),
        Binding("q,Q", "quit", "Quit"),
    ]

    TITLE = "Claude Token Tracker"
    SUB_TITLE = "↑↓ navigate · Enter drill-down · R refresh · P plan · Q quit"

    # Internal state
    _sessions_data: list[dict] = []
    _selected_session: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatsBanner(id="stats-banner")
        yield RateLimitBar(id="rate-limit-bar")
        with TabbedContent(id="tabs"):
            with TabPane("Sessions", id="tab-sessions"):
                with Vertical(id="sessions-pane"):
                    yield SessionsTable(id="sessions-table")
                    yield SessionDetail(id="session-detail")
            with TabPane("Projects", id="tab-projects"):
                yield ProjectsTable(id="projects-table")
            with TabPane("Models", id="tab-models"):
                yield ModelsTable(id="models-table")
            with TabPane("Daily", id="tab-daily"):
                yield DailyChart(id="daily-chart")
        yield Footer()

    def on_mount(self) -> None:
        detail: SessionDetail = self.query_one("#session-detail", SessionDetail)
        detail.clear_detail()
        self.refresh_data()
        # Auto-refresh every 10 seconds
        self.set_interval(10, self.refresh_data)

    def refresh_data(self) -> None:
        """Pull fresh data from the DB and update all widgets."""
        totals = query_totals()
        today = query_today()
        window = query_rolling_window(5)
        sessions = query_sessions()
        projects = query_projects()
        models = query_models()
        daily = query_daily(30)

        self._sessions_data = sessions

        banner: StatsBanner = self.query_one("#stats-banner", StatsBanner)
        banner.update_stats(totals, today)

        rate_bar: RateLimitBar = self.query_one("#rate-limit-bar", RateLimitBar)
        rate_bar.update_bar(window, get_plan(), get_limit())

        sess_table: SessionsTable = self.query_one("#sessions-table", SessionsTable)
        sess_table.populate(sessions)

        proj_table: ProjectsTable = self.query_one("#projects-table", ProjectsTable)
        proj_table.populate(projects)

        mod_table: ModelsTable = self.query_one("#models-table", ModelsTable)
        mod_table.populate(models)

        chart: DailyChart = self.query_one("#daily-chart", DailyChart)
        chart.populate(daily)

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_cycle_plan(self) -> None:
        cycle_plan()
        self.refresh_data()

    @on(DataTable.RowSelected, "#sessions-table")
    def on_session_selected(self, event: DataTable.RowSelected) -> None:
        session_id = str(event.row_key.value)
        session = next(
            (s for s in self._sessions_data if s["session_id"] == session_id), None
        )
        if session:
            self._selected_session = session
            detail: SessionDetail = self.query_one("#session-detail", SessionDetail)
            detail.show_session(session_id, session.get("project_path", "?"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code token usage tracker")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Rescan all Claude projects before opening the dashboard",
    )
    parser.add_argument(
        "--plan",
        choices=PLANS,
        help="Set your Claude subscription plan (pro, max5, max20)",
    )
    args = parser.parse_args()

    init_db()

    if args.plan:
        set_plan(args.plan)
        print(f"Plan set to: {PLAN_NAMES[args.plan]}")

    if args.ingest:
        print("Scanning all Claude Code projects …", end=" ", flush=True)
        turns = list(scan_all_turns())
        count = upsert_turns_bulk(turns)
        print(f"ingested {count} turns.")

    app = TokenTrackerApp()
    app.run()


if __name__ == "__main__":
    main()
