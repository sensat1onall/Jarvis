"""
tradingview.py — open TradingView charts in the user's Chrome and draw on them.

The chart lives in the user's REAL Chrome tab (opened via the system-Chrome
handoff — no automation browser).  Drawing drives TradingView with its own
keyboard shortcuts + mouse clicks on the focused window:

    Alt+T  trend line (2 clicks)      Alt+H  horizontal line (1 click)
    Alt+F  fib retracement (2 clicks) Alt+V  vertical line   (1 click)

Anchor points are chosen by the vision model from a screenshot when possible,
else by safe heuristics inside the chart plot area.  Placement is a sketch of
the strategy — the user fine-tunes by hand.  Returns English strings; the main
loop renders them in Uzbek before speaking.
"""
import base64
import io
import re
import time

_SYMBOLS = {
    "gold": "XAUUSD", "oltin": "XAUUSD", "xau": "XAUUSD", "xauusd": "XAUUSD",
    "altin": "XAUUSD", "золото": "XAUUSD",
    "silver": "XAGUSD", "kumush": "XAGUSD",
    "btc": "BTCUSD", "bitcoin": "BTCUSD", "bitkoin": "BTCUSD",
    "eth": "ETHUSD", "ethereum": "ETHUSD",
}

_TOOL_SPECS = {
    "trend":  {"hotkey": ("alt", "t"), "points": 2, "desc": "trend line"},
    "level":  {"hotkey": ("alt", "h"), "points": 1, "desc": "horizontal support/resistance line"},
    "hline":  {"hotkey": ("alt", "h"), "points": 1, "desc": "horizontal support/resistance line"},
    "horizontal": {"hotkey": ("alt", "h"), "points": 1, "desc": "horizontal support/resistance line"},
    "fib":    {"hotkey": ("alt", "f"), "points": 2, "desc": "Fibonacci retracement"},
    "fibonacci": {"hotkey": ("alt", "f"), "points": 2, "desc": "Fibonacci retracement"},
    "vline":  {"hotkey": ("alt", "v"), "points": 1, "desc": "vertical line"},
}

_DEFAULT_WHERE = {
    "trend": "following the visible trend, connecting the recent swing lows (uptrend) or swing highs (downtrend)",
    "fib":   "from the most recent significant swing low to the swing high",
    "level": "at the most recent major support or resistance level",
    "vline": "at the most recent major reversal candle",
}


def _norm_symbol(raw) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return "XAUUSD"
    return _SYMBOLS.get(s, s.upper().replace(" ", "").replace("/", ""))


def _chart_region(w: int, h: int) -> tuple:
    """Safe drawable area — avoids TradingView's left drawing toolbar, top bar,
    right price scale and bottom timeline."""
    return int(w * 0.20), int(h * 0.18), int(w * 0.84), int(h * 0.78)


def _clamp(pt: tuple, w: int, h: int) -> tuple:
    x0, y0, x1, y1 = _chart_region(w, h)
    return (min(max(int(pt[0]), x0), x1), min(max(int(pt[1]), y0), y1))


def _fallback_points(w: int, h: int, tool: str) -> list:
    x0, y0, x1, y1 = _chart_region(w, h)
    dx, dy = x1 - x0, y1 - y0
    if _TOOL_SPECS.get(tool, _TOOL_SPECS["trend"])["points"] == 1:
        return [(x0 + dx // 2, y0 + dy // 2)]
    if tool in ("fib", "fibonacci"):
        return [(x0 + int(dx * 0.25), y1 - int(dy * 0.12)),
                (x0 + int(dx * 0.75), y0 + int(dy * 0.15))]
    return [(x0 + int(dx * 0.12), y1 - int(dy * 0.18)),
            (x1 - int(dx * 0.12), y0 + int(dy * 0.42))]


def _parse_points(text: str) -> list:
    pairs = re.findall(r"(\d{2,5})\s*[,;x]\s*(\d{2,5})", text or "")
    return [(int(a), int(b)) for a, b in pairs]


def _vision_points(tool: str, where: str, w: int, h: int):
    """Screenshot → vision model → anchor points.  Returns a list of points,
    'NO_CHART', or None (vision unavailable/failed)."""
    try:
        import pyautogui
        from core.llm_client import call_vision
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        spec = _TOOL_SPECS.get(tool, _TOOL_SPECS["trend"])
        n    = spec["points"]
        prompt = (
            f"This is a {w}x{h} pixel screenshot of the user's screen. "
            f"If a TradingView candlestick chart is visible, give pixel coordinates "
            f"to draw a {spec['desc']} {where}. "
            f"Reply ONLY with {'one point as: x,y' if n == 1 else 'two points as: x1,y1;x2,y2 (left point first)'}. "
            f"Points must be INSIDE the chart plot area (not on toolbars). "
            f"If no TradingView chart is visible, reply exactly: NO_CHART"
        )
        text = call_vision(b64, prompt, mime="image/png", timeout=40)
        if "NO_CHART" in (text or "").upper():
            return "NO_CHART"
        pts = _parse_points(text)
        return pts if pts else None
    except Exception as e:
        print(f"[TradingView] vision failed: {e}")
        return None


def _open_chart(symbol: str) -> str:
    from actions.browser_control import open_in_system_chrome
    url = f"https://www.tradingview.com/chart/?symbol={symbol}"
    r = open_in_system_chrome(url)
    if r.startswith("Opened"):
        return (f"TradingView {symbol} chart is opening in the user's Chrome tab. "
                f"Now ask the user which strategy to draw on it "
                f"(trend line / support-resistance levels / fibonacci).")
    return r


def _draw(tool: str, where: str, player=None) -> str:
    spec = _TOOL_SPECS.get(tool)
    if spec is None:
        return (f"Unknown drawing tool '{tool}'. "
                f"Available: trend, level (horizontal), fib, vline.")
    try:
        import pyautogui
    except ImportError:
        return "pyautogui is not installed — cannot draw."

    from actions.computer_control import _focus_window
    fr = _focus_window("TradingView")
    if not fr.startswith("Focused window:"):
        fr = _focus_window("Chrome")
        if not fr.startswith("Focused window:"):
            return "No Chrome window with TradingView found — open the chart first."
    time.sleep(0.7)

    w, h = pyautogui.size()
    where = where or _DEFAULT_WHERE.get(tool, "")
    pts = _vision_points(tool, where, w, h)
    if pts == "NO_CHART":
        return "No TradingView chart is visible in Chrome — open the chart first."
    used_vision = bool(pts)
    if not pts:
        pts = _fallback_points(w, h, tool)
    pts = [_clamp(p, w, h) for p in pts][: spec["points"]]
    while len(pts) < spec["points"]:
        pts.append(_fallback_points(w, h, tool)[-1])

    if player:
        try:
            player.write_log(f"[tradingview] draw {tool} @ {pts} ({'vision' if used_vision else 'heuristic'})")
        except Exception:
            pass

    # Focus the chart with a bare click (no tool active yet → harmless),
    # then activate the drawing tool and place its anchor point(s).
    pyautogui.click(*pts[0]); time.sleep(0.3)
    pyautogui.hotkey(*spec["hotkey"]); time.sleep(0.4)
    pyautogui.click(*pts[0]); time.sleep(0.35)
    if spec["points"] == 2:
        pyautogui.moveTo(*pts[1], duration=0.3)
        pyautogui.click(); time.sleep(0.25)

    placement = "vision-guided" if used_vision else "approximate"
    return (f"Drew a {spec['desc']} on the chart ({placement} placement — "
            f"the user can adjust the anchor points by dragging).")


# TradingView interval codes you get by typing on a focused chart (then Enter).
_TF_MAP = {
    "1m": "1", "1": "1", "2m": "2", "3m": "3", "5m": "5", "10m": "10",
    "15m": "15", "30m": "30", "45m": "45",
    "1h": "60", "60": "60", "2h": "120", "120": "120", "3h": "180",
    "4h": "240", "240": "240",
    "1d": "1D", "d": "1D", "daily": "1D", "1w": "1W", "weekly": "1W",
    "1mo": "1M", "monthly": "1M",
}


def _norm_tf(value):
    s = (value or "").strip().lower().replace(" ", "")
    if s in _TF_MAP:
        return _TF_MAP[s]
    if s.isdigit():
        return s
    return None


def _focus_chart() -> str:
    """Focus the TradingView (or Chrome) window and click a neutral chart spot.
    Returns '' on success or an error message."""
    import pyautogui
    from actions.computer_control import _focus_window
    fr = _focus_window("TradingView")
    if not fr.startswith("Focused window:"):
        fr = _focus_window("Chrome")
        if not fr.startswith("Focused window:"):
            return "No TradingView chart window found — open the chart first."
    time.sleep(0.6)
    w, h = pyautogui.size()
    pyautogui.press("escape")              # drop any active drawing tool
    time.sleep(0.15)
    pyautogui.click(int(w * 0.5), int(h * 0.5))   # focus the chart (harmless click)
    time.sleep(0.3)
    return ""


def _vision_find(description: str):
    """Screenshot → vision model → a single (x, y) for a UI element, or None."""
    try:
        import pyautogui
        from core.llm_client import call_vision
        img = pyautogui.screenshot()
        buf = io.BytesIO(); img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        w, h = pyautogui.size()
        prompt = (
            f"This is a {w}x{h} screenshot of TradingView open in a browser. "
            f"Give the pixel coordinates of {description}. "
            f"Reply with ONLY the coordinates as: x,y . If not visible, reply: NOT_FOUND"
        )
        text = call_vision(b64, prompt, mime="image/png", timeout=40)
        if "NOT_FOUND" in (text or "").upper():
            return None
        m = re.search(r"(\d{2,5})\s*,\s*(\d{2,5})", text or "")
        return (int(m.group(1)), int(m.group(2))) if m else None
    except Exception as e:
        print(f"[TradingView] vision_find failed: {e}")
        return None


def _focus_tv() -> str:
    """Bring the TradingView/Chrome window to the front.  '' on success."""
    from actions.computer_control import _focus_window
    fr = _focus_window("TradingView")
    if not fr.startswith("Focused window:"):
        fr = _focus_window("Chrome")
        if not fr.startswith("Focused window:"):
            return "No TradingView chart window found — open the chart first."
    time.sleep(0.8)
    return ""


def _set_timeframe(value, player=None) -> str:
    try:
        import pyautogui
    except ImportError:
        return "pyautogui is not installed."
    tv = _norm_tf(value)
    if not tv:
        return f"Unknown timeframe '{value}'. Try 1m, 5m, 15m, 1h, 4h, 1D."
    label = (value or "").strip()
    err = _focus_tv()
    if err:
        return err
    if player:
        try: player.write_log(f"[tradingview] timeframe {value} -> {tv}")
        except Exception: pass
    # Primary: click the labelled button in the top timeframe toolbar (reliable).
    coords = _vision_find(
        f"the timeframe button labelled '{label}' in the top toolbar row of "
        f"intervals (like 1m 2m 3m 5m 15m 30m 1h 4h)"
    )
    if coords:
        pyautogui.click(*coords)
        time.sleep(0.3)
        return f"Switched the chart to the {value} timeframe."
    # Fallback: type the interval code on the focused chart, then Enter.
    w, h = pyautogui.size()
    pyautogui.click(int(w * 0.5), int(h * 0.5))
    time.sleep(0.3)
    pyautogui.typewrite(tv, interval=0.08)
    time.sleep(0.4)
    pyautogui.press("enter")
    time.sleep(0.3)
    return f"Switched the chart to the {value} timeframe."


def _add_indicator(name, player=None) -> str:
    try:
        import pyautogui
    except ImportError:
        return "pyautogui is not installed."
    nm = (name or "").strip()
    if not nm:
        return "Which indicator should I add?"
    err = _focus_tv()
    if err:
        return err
    if player:
        try: player.write_log(f"[tradingview] indicator {nm}")
        except Exception: pass
    # Primary: click the 'Indicators' button in the top toolbar to open the search.
    coords = _vision_find("the 'Indicators' button in the top toolbar")
    if coords:
        pyautogui.click(*coords)
        time.sleep(1.0)
    else:
        # Fallback: TradingView '/' shortcut opens the indicator search dialog.
        w, h = pyautogui.size()
        pyautogui.click(int(w * 0.5), int(h * 0.5))
        time.sleep(0.3)
        pyautogui.press("/")
        time.sleep(0.9)
    try:
        import pyperclip
        pyperclip.copy(nm)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pyautogui.typewrite(nm, interval=0.05)
    time.sleep(1.3)                 # wait for search results
    pyautogui.press("enter")        # add the top match
    time.sleep(0.3)
    pyautogui.press("escape")       # close the dialog
    return f"Added the {nm} indicator to the chart."


def tradingview(parameters: dict = None, response=None, player=None,
                session_memory=None, speak=None) -> str:
    p      = parameters or {}
    action = (p.get("action") or "open").lower().strip()
    symbol = _norm_symbol(p.get("symbol"))

    if player:
        try:
            player.write_log(f"[tradingview] {action} {symbol}")
        except Exception:
            pass

    try:
        if action in ("open", "chart", "show"):
            return _open_chart(symbol)
        if action == "draw":
            tool  = (p.get("tool") or "trend").lower().strip()
            where = (p.get("where") or "").strip()
            return _draw(tool, where, player=player)
        if action in ("timeframe", "interval", "tf"):
            return _set_timeframe(p.get("value") or p.get("timeframe") or p.get("tool"), player=player)
        if action in ("indicator", "add_indicator"):
            return _add_indicator(p.get("name") or p.get("indicator") or p.get("value"), player=player)
        return f"Unknown tradingview action: '{action}'. Use open, draw, timeframe or indicator."
    except Exception as e:
        return f"TradingView error: {e}"
