"""
screenshot.py — full-screen / per-monitor / app-targeted screenshots.

Captures with mss (real multi-monitor support) and saves a PNG to Pictures.
NEVER enters Windows' Win+Shift+S "select a region" snip mode (which left the
old `take_screenshot` stuck waiting for a region selection).

target options:
  ''/'current' → the monitor you're looking at (active window's screen)
  'all'        → every monitor stitched into one image
  '1' / '2'    → that specific monitor
  an app name  → the monitor where that app's window is open (e.g. 'chrome')

Returns a short English string; the main loop renders it in Uzbek.
"""
import platform
from datetime import datetime
from pathlib import Path

_OS = platform.system()


def _save_path() -> Path:
    base = Path.home() / "Pictures"
    if not base.exists():
        base = Path.home() / "Desktop"
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base / f"screenshot_{ts}.png"


def _monitors() -> list:
    import mss
    with mss.mss() as sct:
        return list(sct.monitors)        # [0] = all combined, [1..n] = each monitor


def _which_monitor(cx: int, cy: int, mons: list):
    for i, m in enumerate(mons):
        if i == 0:
            continue
        if m["left"] <= cx < m["left"] + m["width"] and m["top"] <= cy < m["top"] + m["height"]:
            return i
    return None


def _monitor_for_app(app_name: str, mons: list):
    try:
        import pygetwindow as gw
    except Exception:
        return None
    name = app_name.lower().strip()
    for w in gw.getAllWindows():
        try:
            title = (w.title or "")
            if (title and name in title.lower() and getattr(w, "visible", True)
                    and (w.width or 0) > 200 and (w.height or 0) > 150):
                return _which_monitor(w.left + w.width // 2, w.top + w.height // 2, mons)
        except Exception:
            continue
    return None


def _active_monitor(mons: list):
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        if w and (w.width or 0) > 100 and (w.height or 0) > 100:
            return _which_monitor(w.left + w.width // 2, w.top + w.height // 2, mons)
    except Exception:
        pass
    return None


def _grab(monitor_index, mons: list) -> str:
    import mss
    import mss.tools
    out = _save_path()
    with mss.mss() as sct:
        if monitor_index is None or not (0 <= monitor_index < len(mons)):
            region = mons[0]             # whole virtual desktop (all monitors)
        else:
            region = mons[monitor_index]
        img = sct.grab(region)
        mss.tools.to_png(img.rgb, img.size, output=str(out))
    return str(out)


def screenshot(parameters: dict = None, response=None, player=None,
               session_memory=None, speak=None) -> str:
    p      = parameters or {}
    target = str(p.get("target") or p.get("monitor") or p.get("app") or "").lower().strip()

    try:
        mons   = _monitors()
        n_real = max(0, len(mons) - 1)

        if n_real <= 1:
            idx, used = (1 if n_real == 1 else None), "the screen"
        elif target in ("", "current", "active", "this", "hozirgi"):
            idx  = _active_monitor(mons)
            used = f"monitor {idx}" if idx else "all screens"
        elif target in ("all", "everything", "full", "both", "hammasi", "screen"):
            idx, used = None, "all screens"
        elif target in ("1", "monitor 1", "primary", "main", "first", "birinchi"):
            idx, used = 1, "monitor 1"
        elif target in ("2", "monitor 2", "second", "ikkinchi"):
            idx, used = (2 if n_real >= 2 else 1), "monitor 2"
        elif target.isdigit():
            k = int(target)
            idx, used = (k if 1 <= k <= n_real else None), f"monitor {k}"
        else:
            m = _monitor_for_app(target, mons)
            idx, used = (m, f"the screen with {target}") if m else (None, "all screens")

        path = _grab(idx, mons)
        if player:
            try: player.write_log(f"[screenshot] {used} -> {path}")
            except Exception: pass
        return f"Screenshot of {used} saved to Pictures."
    except Exception as e:
        # Fallback: pyautogui grabs the full virtual/primary screen (still no snip).
        try:
            import pyautogui
            out = _save_path()
            pyautogui.screenshot(str(out))
            if player:
                try: player.write_log(f"[screenshot] fallback -> {out}")
                except Exception: pass
            return "Screenshot saved to Pictures."
        except Exception as e2:
            return f"Could not take a screenshot: {e2}"
