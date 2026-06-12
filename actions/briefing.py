"""
briefing.py — the morning briefing: ONE spoken summary that combines the
date/time, live weather, key exchange rates and today's upcoming reminders.

  action="now"      (default) → build the briefing and return it
  action="schedule" time=HH:MM → set a recurring DAILY auto-briefing (Windows)
  action="cancel"              → remove the daily auto-briefing

The auto-briefing is a trivial daily scheduled task that just drops the
__BRIEFING__ sentinel into the speech inbox; the running app then computes the
live briefing and speaks it (see core/speech_bridge + main.py inbox worker).

`morning_briefing` returns a short ENGLISH summary; the main loop's LLM round
(it is in _NEEDS_LLM_ROUND) presents it as a natural spoken Uzbek briefing.
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_BRIEF_TASK = "JARVISDailyBriefing"


def _config_city() -> str:
    try:
        base = Path(__file__).resolve().parent.parent
        cfg = json.loads((base / "config" / "api_keys.json").read_text(encoding="utf-8"))
        return (cfg.get("city") or cfg.get("user_city") or "Tashkent").strip() or "Tashkent"
    except Exception:
        return "Tashkent"


def _todays_reminders() -> list[str]:
    """Upcoming reminders for the rest of today, as 'HH:MM message' strings."""
    try:
        log = Path.home() / ".jarvis" / "reminders.json"
        if not log.exists():
            return []
        arr = json.loads(log.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    now    = datetime.now()
    today  = now.strftime("%Y-%m-%d")
    now_hm = now.strftime("%H:%M")
    out = []
    for r in arr:
        t = str(r.get("time", ""))
        if t.startswith(today):
            hm = t.split(" ", 1)[1] if " " in t else ""
            if hm and hm >= now_hm:               # only what's still ahead today
                out.append(f"{hm} — {r.get('message', '')}".strip())
    return out


def _gather(city: str) -> str:
    now   = datetime.now()
    parts = [f"Briefing for {now.strftime('%A, %B %d')}, the time is {now.strftime('%H:%M')}."]

    # Live weather (text, so it can be spoken).  A valid wttr.in line legitimately
    # contains ONE '%' (humidity); unexpanded format codes (%t %f %w …) would give
    # many — so reject only when there are several, matching weather_report.
    try:
        from actions.weather_report import _wttr
        w = _wttr(city)
        if w and w.count("%") <= 2 and "Unknown" not in w:
            parts.append(f"Weather — {w}.")
    except Exception:
        pass

    # Key exchange rates (USD + EUR).
    try:
        from actions.uzbek_info import _currency
        usd = _currency("USD")
        eur = _currency("EUR")
        rates = "; ".join(x for x in (usd, eur) if x and "Could not" not in x)
        if rates:
            parts.append(f"Exchange rates — {rates}.")
    except Exception:
        pass

    # Today's remaining reminders.
    rem = _todays_reminders()
    if rem:
        parts.append("Reminders still ahead today: " + "; ".join(rem) + ".")
    else:
        parts.append("No more reminders scheduled for today.")

    return " ".join(parts)


# ── daily auto-briefing scheduling (Windows) ───────────────────────────────
def _brief_trigger_script() -> Path:
    """A tiny standalone script that drops the __BRIEFING__ sentinel into the
    speech inbox; run by the daily scheduled task."""
    d = Path.home() / ".jarvis"
    d.mkdir(parents=True, exist_ok=True)
    sp = d / "daily_briefing_trigger.py"
    sp.write_text(
        "import json, time, os, pathlib\n"
        "inbox = pathlib.Path.home() / '.jarvis' / 'speech_inbox'\n"
        "inbox.mkdir(parents=True, exist_ok=True)\n"
        "f = inbox / ('brief_%s_%d.json' % (time.strftime('%Y%m%d_%H%M%S'), os.getpid()))\n"
        "f.write_text(json.dumps({'text': '__BRIEFING__'}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    return sp


def _schedule_daily(hhmm: str) -> str:
    hhmm = (hhmm or "08:00").strip()
    try:
        hhmm = datetime.strptime(hhmm, "%H:%M").strftime("%H:%M")
    except ValueError:
        return "Please give the briefing time as HH:MM in 24-hour form, e.g. 08:00."
    if sys.platform != "win32":
        return "Automatic daily briefing scheduling is only wired up for Windows right now."

    py  = Path(sys.executable)
    pyw = py.parent / "pythonw.exe"            # no console window when it fires
    if pyw.exists():
        py = pyw
    script = _brief_trigger_script()
    tr = f'"{py}" "{script}"'
    res = subprocess.run(
        ["schtasks", "/Create", "/TN", _BRIEF_TASK, "/SC", "DAILY",
         "/ST", hhmm, "/TR", tr, "/F"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip()
        print(f"[Briefing] schtasks failed: {err}")
        return "I couldn't schedule the daily briefing with the system scheduler."
    return f"Daily morning briefing scheduled for {hhmm} every day."


def _cancel_daily() -> str:
    if sys.platform != "win32":
        return "There's no scheduled briefing to cancel."
    res = subprocess.run(
        ["schtasks", "/Delete", "/TN", _BRIEF_TASK, "/F"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return "There was no daily briefing scheduled."
    return "Daily morning briefing cancelled."


# ── public entry point ─────────────────────────────────────────────────────
def morning_briefing(parameters: dict = None, response=None, player=None,
                     session_memory=None, speak=None) -> str:
    p      = parameters or {}
    action = (p.get("action") or "now").lower().strip()
    city   = (p.get("city") or "").strip() or _config_city()
    if player:
        try: player.write_log(f"[briefing] {action}")
        except Exception: pass

    if action in ("schedule", "set", "daily", "auto", "every_day"):
        return _schedule_daily(p.get("time") or "08:00")
    if action in ("cancel", "stop", "off", "unschedule", "remove"):
        return _cancel_daily()
    return _gather(city)
