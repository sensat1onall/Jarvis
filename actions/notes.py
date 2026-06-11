"""
notes.py — quick personal notes and named lists for JARVIS.

Stored in ~/.jarvis/notes.json:
    { "notes": [{"text": "...", "ts": "..."}, ...],
      "lists": { "shopping": ["milk", ...], "todo": [...] } }

Returns a short user-ready English string; the main loop renders it in Uzbek
(via _to_uzbek) before speaking.
"""
import json
from datetime import datetime
from pathlib import Path


def _store_path() -> Path:
    d = Path.home() / ".jarvis"
    d.mkdir(parents=True, exist_ok=True)
    return d / "notes.json"


def _load() -> dict:
    p = _store_path()
    if not p.exists():
        return {"notes": [], "lists": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"notes": [], "lists": {}}
        data.setdefault("notes", [])
        data.setdefault("lists", {})
        return data
    except Exception:
        return {"notes": [], "lists": {}}


def _save(data: dict) -> None:
    _store_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def notes(parameters: dict = None, response=None, player=None,
          session_memory=None, speak=None) -> str:
    p         = parameters or {}
    action    = (p.get("action") or "").lower().strip()
    text      = (p.get("text") or "").strip()
    list_name = (p.get("list") or "").strip().lower() or "list"
    item      = (p.get("item") or "").strip() or text

    if player:
        try:
            player.write_log(f"[notes] {action} {text or item or list_name}")
        except Exception:
            pass

    data = _load()

    # ── plain notes ──────────────────────────────────────────────────────
    if action in ("add", "add_note", "note", "save", "remember"):
        if not text:
            return "What should I note down?"
        data["notes"].append({"text": text, "ts": datetime.now().strftime("%Y-%m-%d %H:%M")})
        _save(data)
        return f"Noted: {text}"

    if action in ("list", "list_notes", "show_notes", "read", "show", "read_notes"):
        ns = data.get("notes", [])
        if not ns:
            return "You have no notes yet."
        lines = [f"{i+1}. {n['text']}" for i, n in enumerate(ns[-10:])]
        return "Your notes: " + "; ".join(lines)

    if action in ("clear_notes", "delete_notes", "clear"):
        data["notes"] = []
        _save(data)
        return "All notes cleared."

    # ── named lists ──────────────────────────────────────────────────────
    if action in ("add_to_list", "add_item", "list_add"):
        if not item:
            return "What should I add to the list?"
        data["lists"].setdefault(list_name, []).append(item)
        _save(data)
        return f"Added {item} to the {list_name} list."

    if action in ("show_list", "read_list", "list_items"):
        items = data.get("lists", {}).get(list_name, [])
        if not items:
            return f"The {list_name} list is empty."
        return f"{list_name} list: " + ", ".join(items)

    if action in ("remove_item", "remove_from_list"):
        items = data.get("lists", {}).get(list_name, [])
        if item and item in items:
            items.remove(item)
            _save(data)
            return f"Removed {item} from the {list_name} list."
        return f"{item} is not on the {list_name} list."

    if action in ("clear_list", "delete_list"):
        data["lists"].pop(list_name, None)
        _save(data)
        return f"Cleared the {list_name} list."

    # ── fallback: if free text was given, treat it as a note ─────────────
    if text:
        data["notes"].append({"text": text, "ts": datetime.now().strftime("%Y-%m-%d %H:%M")})
        _save(data)
        return f"Noted: {text}"

    return ("Notes: say 'note that ...', 'show my notes', "
            "'add X to the shopping list', or 'show my shopping list'.")
