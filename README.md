# Claude Token Tracker

An interactive terminal dashboard that tracks token usage and API cost across all your [Claude Code](https://claude.ai/claude-code) sessions — in real time, with no proxy or configuration required.

## How it works

Claude Code saves every session as a JSONL file in `~/.claude/projects/`. Each assistant turn includes precise token counts (input, output, cache reads/writes). This tool:

1. Parses those files to extract token usage
2. Stores aggregates in a local SQLite database (`~/.claude/token_tracker.db`)
3. Hooks into Claude Code's `Stop` event to ingest data automatically after every turn
4. Displays everything in a live, interactive TUI

## Features

- **4 views** — Sessions, Projects, Models, Daily usage chart
- **Per-session drill-down** — see every turn with token breakdown and cost
- **Accurate cost calculation** — accounts for input, output, cache-write, and cache-read tokens separately
- **Auto-refresh** every 10 seconds
- **Hook-driven** — updates silently in the background while you work
- **Historical backfill** — ingests all past sessions on first run

## Requirements

- Python 3.8+
- [Claude Code](https://claude.ai/claude-code) CLI

## Installation

```bash
git clone https://github.com/ak27serg/claude-token-tracker.git
cd claude-token-tracker
pip install -r requirements.txt
```

### Install the Stop hook

This wires the tracker into Claude Code so it updates automatically after every session turn:

```bash
python3 setup_hooks.py
```

This edits `~/.claude/settings.json` (a backup is created automatically). To remove the hook later:

```bash
python3 setup_hooks.py remove
```

## Usage

### First run — backfill all historical sessions

```bash
python3 dashboard.py --ingest
```

### Subsequent runs

```bash
python3 dashboard.py
```

The database is kept up to date by the Stop hook, so the dashboard reflects your latest sessions immediately.

### Manual ingest (without opening the dashboard)

```bash
python3 ingest.py < /dev/null
```

## Dashboard

```
╭─────────────────────────────── Claude Token Tracker ───────────────────────────────╮
│ All-time: 2.8M tokens | $2.31 | 4 sessions | 104 turns   Today: 1.1M | $0.91      │
├──────────────────────────────────────────────────────────────────────────────────── │
│ Sessions │ Projects │ Models │ Daily                                                │
├──────────────────────────────────────────────────────────────────────────────────── │
│ Last Active       Project                   Model       Turns  Input   Output  Cost │
│ 2026-02-26 03:14  ~/projects/claude/track…  sonnet-4-6  44     1.2K    18.3K  $1.11│
│ 2026-02-26 02:33  ~/projects/claude/cours…  sonnet-4-6  39     850     22.1K  $0.77│
│ ...                                                                                 │
├──────────────────────────────────────────────────────────────────────────────────── │
│ ~/projects/claude/token_tracker · 44 turns · session 6c4d19cc…                     │
│ Timestamp          Input   Output  Cache-R  Cache-W  Total    Cost                 │
│ 2026-02-26 03:01   3       0       18.7K    1.2K     19.9K    $0.008               │
│ 2026-02-26 03:01   3       133     18.7K    1.3K     20.1K    $0.009               │
│ ...                                                                                 │
╰─────────────────────────────────────────────────────────────────────────────────────╯
```

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate table rows |
| `Enter` | Drill into selected session |
| `R` / `F5` | Refresh data |
| `Q` | Quit |

**Tabs:**

| Tab | Shows |
|-----|-------|
| Sessions | All sessions sorted by last activity; click for per-turn breakdown |
| Projects | Aggregated cost and token usage by project directory |
| Models | Breakdown by model (useful if you mix Sonnet, Opus, Haiku) |
| Daily | ASCII bar chart of token usage over the last 30 days |

## Token types explained

Claude Code uses [prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching), so each turn reports four token counts:

| Field | Description | Relative cost |
|-------|-------------|---------------|
| Input | Tokens processed fresh | 1× |
| Output | Tokens generated | 5× |
| Cache-W | Tokens written to cache | 1.25× |
| Cache-R | Tokens read from cache (already cached) | 0.1× |

Cache reads are 10× cheaper than regular input — this is why long Claude Code sessions become more cost-efficient over time.

## Pricing

Pricing is defined in `tracker/pricing.py` and can be updated if Anthropic changes their rates:

| Model | Input | Output | Cache-Write | Cache-Read |
|-------|-------|--------|-------------|------------|
| claude-sonnet-4-6 | $3.00 | $15.00 | $3.75 | $0.30 |
| claude-opus-4-6   | $15.00 | $75.00 | $18.75 | $1.50 |
| claude-haiku-4-5  | $0.80 | $4.00 | $1.00 | $0.08 |

*Prices in USD per million tokens.*

## Project structure

```
claude-token-tracker/
├── tracker/
│   ├── pricing.py    # Model pricing table and cost calculation
│   ├── parser.py     # JSONL parsing → Turn records
│   └── db.py         # SQLite storage and query helpers
├── dashboard.py      # Textual TUI (entry point)
├── ingest.py         # Hook script (called by Claude Code on Stop)
├── setup_hooks.py    # Installs/removes the Claude Code Stop hook
└── requirements.txt
```

## Data

- **Source**: `~/.claude/projects/**/*.jsonl` (written by Claude Code, read-only)
- **Database**: `~/.claude/token_tracker.db` (SQLite, gitignored)
- No data leaves your machine.

## License

MIT
