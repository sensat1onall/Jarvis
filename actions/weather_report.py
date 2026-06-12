"""
weather_report.py — fetch the live weather as TEXT (so JARVIS can SPEAK it),
via wttr.in (free, no API key).  Falls back to opening a Google weather search
in the browser only if the fetch fails.
"""
import urllib.request as _u
from urllib.parse import quote, quote_plus


def _wttr(city: str) -> str:
    # wttr.in returns the formatted one-liner only for curl-like clients.
    url = (f"https://wttr.in/{quote(city)}"
           f"?format=%l:+%c+%C,+%t+(feels+%f),+wind+%w,+humidity+%h&m")
    req = _u.Request(url, headers={"User-Agent": "curl/8.0"})
    with _u.urlopen(req, timeout=12) as r:
        return r.read().decode("utf-8", "replace").strip()


def weather_action(parameters: dict, player=None, session_memory=None) -> str:
    city = (parameters.get("city") or "").strip() or "Tashkent"
    when = (parameters.get("time") or "").strip()
    if player:
        try: player.write_log(f"[weather] {city}")
        except Exception: pass

    # Live fetch first — so the assistant can actually tell the user the weather.
    try:
        txt = _wttr(city)
        bad = (not txt) or ("Unknown location" in txt) or ("Sorry" in txt) or txt.count("%") > 2
        if not bad:
            return f"Weather — {txt}"
    except Exception as e:
        print(f"[Weather] wttr.in failed: {e}")

    # Fallback: open a Google weather search in the browser.
    try:
        import webbrowser
        q = f"weather in {city} {when}".strip()
        webbrowser.open(f"https://www.google.com/search?q={quote_plus(q)}")
        return f"I opened the weather for {city} in the browser."
    except Exception as e:
        return f"Could not get the weather for {city}: {e}"
