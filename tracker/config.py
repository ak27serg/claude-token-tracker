"""
Plan configuration for rate-limit progress bar.

Config file: ~/.claude/token_tracker_config.json
"""

from __future__ import annotations

import json
import os

CONFIG_PATH = os.path.expanduser("~/.claude/token_tracker_config.json")

# Approximate output-token limits per 5-hour rolling window
PLAN_LIMITS = {
    "pro": 44_000,
    "max5": 88_000,
    "max20": 220_000,
}

PLAN_NAMES = {
    "pro": "Pro",
    "max5": "Max 5x",
    "max20": "Max 20x",
}

PLANS = list(PLAN_LIMITS.keys())


def _load() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def get_plan() -> str:
    return _load().get("plan", "pro")


def set_plan(plan: str) -> None:
    if plan not in PLAN_LIMITS:
        raise ValueError(f"Unknown plan: {plan!r}. Choose from {PLANS}")
    cfg = _load()
    cfg["plan"] = plan
    _save(cfg)


def get_limit() -> int:
    return PLAN_LIMITS.get(get_plan(), PLAN_LIMITS["pro"])


def cycle_plan() -> str:
    """Advance to the next plan and return it."""
    current = get_plan()
    idx = PLANS.index(current) if current in PLANS else 0
    next_plan = PLANS[(idx + 1) % len(PLANS)]
    set_plan(next_plan)
    return next_plan
