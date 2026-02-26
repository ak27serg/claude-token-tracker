#!/usr/bin/env python3
"""
Install (or update) the Claude Code Stop hook so that ingest.py runs
automatically after every Claude Code session turn.

Edits ~/.claude/settings.json in-place, preserving existing settings.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime

SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
INGEST_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingest.py")
PYTHON = sys.executable

HOOK_COMMAND = f"{PYTHON} {INGEST_SCRIPT}"


def load_settings(path: str) -> dict:
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {}


def save_settings(path: str, settings: dict) -> None:
    # Backup first
    if os.path.isfile(path):
        backup = path + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, backup)
        print(f"  Backed up existing settings to {backup}")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def hook_already_installed(hooks_list: list) -> bool:
    for entry in hooks_list:
        for h in entry.get("hooks", []):
            if INGEST_SCRIPT in h.get("command", ""):
                return True
    return False


def install_hook() -> None:
    print(f"Loading settings from {SETTINGS_PATH} ...")
    settings = load_settings(SETTINGS_PATH)

    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    if hook_already_installed(stop_hooks):
        print("Hook is already installed. Nothing to do.")
        return

    stop_hooks.append(
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": HOOK_COMMAND,
                }
            ],
        }
    )

    save_settings(SETTINGS_PATH, settings)
    print(f"Hook installed successfully.")
    print(f"  Command: {HOOK_COMMAND}")
    print()
    print("The token tracker will now update automatically after each Claude session.")


def remove_hook() -> None:
    print(f"Loading settings from {SETTINGS_PATH} ...")
    settings = load_settings(SETTINGS_PATH)

    hooks = settings.get("hooks", {})
    stop_hooks = hooks.get("Stop", [])

    if not hook_already_installed(stop_hooks):
        print("Hook is not installed. Nothing to remove.")
        return

    new_stop = []
    for entry in stop_hooks:
        filtered = [
            h for h in entry.get("hooks", [])
            if INGEST_SCRIPT not in h.get("command", "")
        ]
        if filtered:
            new_stop.append({**entry, "hooks": filtered})

    hooks["Stop"] = new_stop
    save_settings(SETTINGS_PATH, settings)
    print("Hook removed.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "install"
    if cmd == "remove":
        remove_hook()
    else:
        install_hook()
