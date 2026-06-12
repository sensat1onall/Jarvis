"""
uzbek_info.py — live Uzbek-relevant lookups + translation.

  currency  : CBU so'm exchange rate          (cbu.uz, free, no key)
  crypto    : coin prices in USD              (CoinGecko, free)
  prayer    : Islamic prayer times            (Aladhan, free)
  news      : today's top Uzbek headlines     (gazeta.uz / daryo.uz RSS)
  translate : translate text to any language  (via the LLM)

All return short English strings; the main loop's LLM round presents them in
natural Uzbek (these tools are in _NEEDS_LLM_ROUND).
"""
import json
import re
import urllib.request as _u


def _get(url: str, timeout: int = 12) -> str:
    req = _u.Request(url, headers={"User-Agent": "Mozilla/5.0 jarvis"})
    with _u.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ── currency (CBU) ───────────────────────────────────────────────────────
_CCY_ALIAS = {"DOLLAR": "USD", "DOLAR": "USD", "EVRO": "EUR", "EURO": "EUR",
              "RUBL": "RUB", "RUBLE": "RUB", "FUNT": "GBP", "POUND": "GBP"}


def _currency(code: str) -> str:
    code = (code or "USD").upper().strip()
    code = _CCY_ALIAS.get(code, code)
    try:
        data = json.loads(_get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/"))
        row = next((x for x in data if x.get("Ccy") == code), None)
        if row:
            return f"{row['Ccy']} = {row['Rate']} UZS (Central Bank, {row.get('Date', '')})"
        return f"Currency '{code}' not found."
    except Exception as e:
        return f"Could not get the exchange rate: {e}"


# ── crypto (CoinGecko) ───────────────────────────────────────────────────
_COIN_ALIAS = {"btc": "bitcoin", "bitkoin": "bitcoin", "eth": "ethereum",
               "bnb": "binancecoin", "sol": "solana", "ton": "the-open-network",
               "xrp": "ripple", "doge": "dogecoin"}


def _crypto(coins) -> str:
    if isinstance(coins, str):
        coins = [c.strip().lower() for c in coins.replace(",", " ").split() if c.strip()]
    coins = [_COIN_ALIAS.get(c, c) for c in (coins or ["bitcoin"])]
    try:
        j = json.loads(_get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coins)}&vs_currencies=usd"))
        parts = [f"{k} = ${v.get('usd')}" for k, v in j.items() if v.get("usd") is not None]
        return "; ".join(parts) if parts else "No crypto data found."
    except Exception as e:
        return f"Could not get crypto prices: {e}"


# ── prayer times (Aladhan) ───────────────────────────────────────────────
def _prayer(city: str) -> str:
    city = (city or "Tashkent").strip()
    try:
        j = json.loads(_get(
            f"https://api.aladhan.com/v1/timingsByCity?city={city}&country=Uzbekistan&method=2"))
        t = j["data"]["timings"]
        return (f"Prayer times for {city} today — Fajr {t['Fajr']}, Sunrise {t['Sunrise']}, "
                f"Dhuhr {t['Dhuhr']}, Asr {t['Asr']}, Maghrib {t['Maghrib']}, Isha {t['Isha']}.")
    except Exception as e:
        return f"Could not get prayer times: {e}"


# ── news (RSS) ───────────────────────────────────────────────────────────
_RSS = ["https://www.gazeta.uz/uz/rss/", "https://daryo.uz/feed",
        "https://kun.uz/news/rss"]


def _news(n: int = 5) -> str:
    for url in _RSS:
        try:
            xml = _get(url, timeout=12)
            raw = re.findall(r"<item>.*?<title>(.*?)</title>", xml, re.S)
            titles = []
            for t in raw:
                t = re.sub(r"<!\[CDATA\[|\]\]>", "", t)
                t = re.sub(r"<.*?>", "", t).strip()
                if t:
                    titles.append(t)
            if titles:
                top = titles[: max(1, min(n, 8))]
                return "Top news headlines: " + " | ".join(top)
        except Exception:
            continue
    return "Could not fetch the news right now."


# ── public entry points ──────────────────────────────────────────────────
def live_info(parameters: dict = None, response=None, player=None,
              session_memory=None, speak=None) -> str:
    p      = parameters or {}
    action = (p.get("action") or "").lower().strip()
    if player:
        try: player.write_log(f"[info] {action}")
        except Exception: pass
    if action in ("currency", "rate", "kurs", "exchange", "valyuta"):
        return _currency(p.get("code") or p.get("currency") or "USD")
    if action in ("crypto", "coin", "kripto"):
        return _crypto(p.get("coins") or p.get("coin") or "bitcoin")
    if action in ("prayer", "namoz", "prayer_times"):
        return _prayer(p.get("city") or "Tashkent")
    if action in ("news", "yangiliklar"):
        try: n = int(p.get("count", 5) or 5)
        except Exception: n = 5
        return _news(n)
    return "Specify what to look up: currency, crypto, prayer, or news."


def translate(parameters: dict = None, response=None, player=None,
              session_memory=None, speak=None) -> str:
    p      = parameters or {}
    text   = (p.get("text") or "").strip()
    target = (p.get("target") or p.get("to") or "English").strip()
    if not text:
        return "What should I translate?"
    if player:
        try: player.write_log(f"[translate] -> {target}")
        except Exception: pass
    try:
        from core.llm_client import call_llm_text
        sysp = (f"You are a professional translator. Translate the user's text into {target}. "
                f"Output ONLY the translation — no quotes, no notes, nothing else.")
        out = call_llm_text(text, system=sysp, timeout=20).strip()
        return f"{target} translation: {out}" if out else "Translation failed."
    except Exception as e:
        return f"Could not translate: {e}"
