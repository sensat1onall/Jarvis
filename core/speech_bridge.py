"""
speech_bridge.py — tiny file-based IPC so out-of-process helpers (a fired
reminder, a scheduled daily briefing) can make the RUNNING JARVIS app SPEAK.

A producer drops a small JSON file ({"text": "..."}) into
~/.jarvis/speech_inbox/.  The app's background poller
(JarvisLocal._speech_inbox_worker) reads it, speaks the text, and deletes the
file.  If the app isn't running, the files simply wait there and are spoken the
next time it starts — reminders are never silently missed.

The fired-reminder script runs standalone (the project is NOT on its sys.path),
so its write side is inlined there with stdlib only (see actions/reminder.py).
This module is the shared, importable version used by the app and the briefing
action.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# A speech item whose text equals this sentinel is expanded by the running app
# into a freshly-computed morning briefing (so the scheduled daily task stays a
# trivial trigger and the live data / Uzbek phrasing happen in-app).
BRIEFING_SENTINEL = "__BRIEFING__"


def inbox_dir() -> Path:
    d = Path.home() / ".jarvis" / "speech_inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def push_speech(text: str) -> Path:
    """Queue one line for the running app to speak.  Returns the file path."""
    d = inbox_dir()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = f"spk_{stamp}_{os.getpid()}"
    p = d / f"{base}.json"
    i = 0
    while p.exists():                       # avoid same-second collisions
        i += 1
        p = d / f"{base}_{i}.json"
    p.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
    return p
