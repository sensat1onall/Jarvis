"""
tv_web.py — control TradingView in a dedicated, JARVIS-driven Chrome (web) via
Playwright/CDP.  Reliable DOM + keyboard control (replaces the brittle
vision-clicking of the old tradingview.py for charting):

  open             — open a symbol's chart            (URL ?symbol=)
  timeframe        — change the interval              (URL &interval=)
  indicator        — add a study (RSI, MACD, SAR…)    (Indicators dialog)
  remove_indicator — remove a study by name, or 'all' (charting API)
  draw             — pick a drawing tool via TradingView HOTKEY, place on canvas
  read             — current symbol / interval / price (DOM)

One persistent, visible browser window is reused across calls.  A dedicated
profile (~/.jarvis_profiles/tradingview) keeps the TradingView login and avoids
locking the user's everyday Chrome profile.
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from urllib.parse import quote

# JARVIS ATTACHES to a normal Chrome launched with --remote-debugging-port (see
# _tv_chrome.bat) instead of letting Playwright launch one — a Playwright-launched
# browser carries automation flags (--no-sandbox, navigator.webdriver) that make
# TradingView throw a bot CAPTCHA on login. A user-launched Chrome is clean, so
# the one-time login captcha is human-solvable. Override the port via TV_CDP_PORT.
_CDP_PORT = os.environ.get("TV_CDP_PORT", "9222")
_CDP_URL = f"http://127.0.0.1:{_CDP_PORT}"
_TV_PROFILE = str(Path.home() / ".jarvis_profiles" / "tv_chrome")


def _launch_debug_chrome() -> bool:
    """Auto-launch a clean Chrome on the CDP port with the dedicated TradingView
    profile (same as tv_chrome.bat) when one isn't already running — so the user
    doesn't have to start it manually. The profile keeps their TradingView login."""
    import subprocess
    cands = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Google", "Chrome", "Application", "chrome.exe"),
    ]
    chrome = next((c for c in cands if c and os.path.exists(c)), None)
    if not chrome:
        return False
    try:
        subprocess.Popen(
            [chrome, f"--remote-debugging-port={_CDP_PORT}", f"--user-data-dir={_TV_PROFILE}",
             "--no-first-run", "--no-default-browser-check",
             "https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


from playwright.async_api import async_playwright, Playwright, BrowserContext, Page

# ── symbol / interval mapping ───────────────────────────────────────────────
_SYMBOLS = {
    "gold": "OANDA:XAUUSD", "oltin": "OANDA:XAUUSD", "xau": "OANDA:XAUUSD",
    "xauusd": "OANDA:XAUUSD",
    "silver": "OANDA:XAGUSD", "kumush": "OANDA:XAGUSD",
    "bitcoin": "BINANCE:BTCUSDT", "btc": "BINANCE:BTCUSDT", "bitkoin": "BINANCE:BTCUSDT",
    "ethereum": "BINANCE:ETHUSDT", "eth": "BINANCE:ETHUSDT",
    "eurusd": "OANDA:EURUSD", "gbpusd": "OANDA:GBPUSD",
    "oil": "TVC:USOIL", "neft": "TVC:USOIL",
    "nasdaq": "NASDAQ:NDX", "sp500": "SP:SPX", "apple": "NASDAQ:AAPL",
    "tesla": "NASDAQ:TSLA",
}

_INTERVALS = {
    "1m": "1", "1": "1", "3m": "3", "5m": "5", "5": "5", "15m": "15", "15": "15",
    "30m": "30", "30": "30", "45m": "45",
    "1h": "60", "60": "60", "2h": "120", "3h": "180", "4h": "240", "240": "240",
    "1d": "1D", "d": "1D", "day": "1D", "kunlik": "1D",
    "1w": "1W", "w": "1W", "week": "1W", "haftalik": "1W", "1mo": "1M", "month": "1M",
}

# TradingView drawing-tool hotkeys (verified from TV docs)
_DRAW_HOTKEYS = {
    "trend": "Alt+t", "trendline": "Alt+t", "line": "Alt+t",
    "horizontal": "Alt+h", "level": "Alt+h", "support": "Alt+h", "resistance": "Alt+h",
    "vertical": "Alt+v", "vline": "Alt+v",
    "fib": "Alt+f", "fibonacci": "Alt+f", "fibo": "Alt+f",
    "cross": "Alt+c", "crossline": "Alt+c",
}


# Map short names → TradingView's canonical indicator title, so we match the
# INDICATOR row (not an "X Strategy" / community script with a similar name).
_IND_NAMES = {
    "rsi": "Relative Strength Index", "macd": "MACD",
    "ma": "Moving Average", "sma": "Moving Average",
    "ema": "Moving Average Exponential",
    "bb": "Bollinger Bands", "bollinger": "Bollinger Bands",
    "stoch": "Stochastic", "stochastic": "Stochastic",
    "atr": "Average True Range", "adx": "Average Directional Index",
    "vwap": "VWAP", "volume": "Volume", "ichimoku": "Ichimoku Cloud",
    # Parabolic SAR + other common studies
    "sar": "Parabolic SAR", "psar": "Parabolic SAR", "parabolic": "Parabolic SAR",
    "supertrend": "Supertrend", "cci": "Commodity Channel Index",
    "mfi": "Money Flow Index", "obv": "On Balance Volume",
    "williams": "Williams %R", "momentum": "Momentum",
    "donchian": "Donchian Channels", "keltner": "Keltner Channels",
    "pivot": "Pivot Points Standard",
}


def _norm_symbol(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "OANDA:XAUUSD"
    key = s.lower().replace(" ", "")
    if key in _SYMBOLS:
        return _SYMBOLS[key]
    return s.upper()                       # already a ticker like "AAPL" / "BINANCE:BTCUSDT"


def _norm_interval(v: str) -> str:
    return _INTERVALS.get((v or "").lower().strip(), "60")


# ── analysis engines (run in the page via the charting JS API) ─────────────
# Each reads the chart's own OHLC bars ([time,o,h,l,c,v] via getSeries().data()),
# computes the strategy's exact points, and draws with createMultipointShape.

# Structure analysis: ZigZag significant pivots -> label A,B,C,D,E at the real
# turning points -> connect the structure (dotted) -> dominant trend line ->
# direction read (up / down / triangle) + a projection arrow for the next move.
_JS_TRENDLINE = r"""() => {
  const ch = window.TradingViewApi.activeChart();
  const sd = ch.getSeries().data();
  const raw = [];
  try { sd.each(function(idx, item){ if (item && item.length >= 5) raw.push(item); }); } catch(e){}
  raw.sort((x,y)=>x[0]-y[0]);
  if (raw.length < 40) return {ok:false, err:'not enough bars ('+raw.length+')'};
  const bars = raw.slice(-Math.min(120, raw.length));     // focus on the recent window
  let maxP=-1e18, minP=1e18;
  for (const b of bars){ if(b[2]>maxP)maxP=b[2]; if(b[3]<minP)minP=b[3]; }
  // ZigZag: a pivot is confirmed once price reverses by > THR (4% of range).
  function zz(THR){
    const piv=[]; let mode=0, hiI=0,hiP=bars[0][2], loI=0,loP=bars[0][3];
    for(let i=1;i<bars.length;i++){
      if(bars[i][2]>hiP){hiP=bars[i][2];hiI=i;}
      if(bars[i][3]<loP){loP=bars[i][3];loI=i;}
      if(mode!==-1 && hiP-bars[i][3]>THR){ piv.push({i:hiI,t:bars[hiI][0],p:hiP,type:'H'}); mode=-1; loP=bars[i][3];loI=i; hiP=bars[i][2];hiI=i; }
      else if(mode!==1 && bars[i][2]-loP>THR){ piv.push({i:loI,t:bars[loI][0],p:loP,type:'L'}); mode=1; hiP=bars[i][2];hiI=i; loP=bars[i][3];loI=i; }
    }
    if(mode===1) piv.push({i:hiI,t:bars[hiI][0],p:hiP,type:'H'});
    else if(mode===-1) piv.push({i:loI,t:bars[loI][0],p:loP,type:'L'});
    return piv;
  }
  // adaptive threshold: coarsen until the recent pivots span a meaningful period
  // (>= ~35 candles) so A–F isn't crammed into the last 10–15 bars.
  let thr=(maxP-minP)*0.05 || 1e-6, piv=zz(thr);
  for(let g=0; g<8; g++){
    const ln=piv.slice(-6);
    const span = ln.length>=2 ? (ln[ln.length-1].i - ln[0].i) : 0;
    if(span>=35 || piv.length<5) break;
    thr*=1.35; piv=zz(thr);
  }
  if(piv.length<3){ piv=zz((maxP-minP)*0.025); }      // too few — try finer
  if(piv.length<3) return {ok:false, err:'not enough significant swings ('+piv.length+')'};
  const last = piv.slice(-6), L=['A','B','C','D','E','F'];
  // label each pivot at its exact turning point
  for(let k=0;k<last.length;k++){ try {
    ch.createShape({time:last[k].t, price:last[k].p},
      {shape:'text', text:L[k], lock:false, disableSelection:true,
       overrides:{color:last[k].type==='H'?'#ef5350':'#089981', fontsize:18, bold:true}});
  } catch(e){} }
  // dotted structure (zigzag) lines between consecutive pivots
  for(let k=1;k<last.length;k++){ try {
    ch.createMultipointShape([{time:last[k-1].t,price:last[k-1].p},{time:last[k].t,price:last[k].p}],
      {shape:'trend_line', lock:false, disableSelection:true, overrides:{linecolor:'#9598a1', linewidth:1, linestyle:2}});
  } catch(e){} }
  // structure read from the last two highs and last two lows
  const H2=last.filter(p=>p.type==='H').slice(-2), Lo=last.filter(p=>p.type==='L').slice(-2);
  let dir='range', mainPts=null;
  if(H2.length===2 && Lo.length===2){
    const hh=H2[1].p>H2[0].p, hl=Lo[1].p>Lo[0].p, lh=H2[1].p<H2[0].p, ll=Lo[1].p<Lo[0].p;
    if(hh&&hl){ dir='uptrend'; mainPts=Lo; }
    else if(lh&&ll){ dir='downtrend'; mainPts=H2; }
    else if(lh&&hl){ dir='triangle'; }
    else dir='range';
  }
  // dominant trend line (support along lows / resistance along highs)
  if(mainPts){ try {
    ch.createMultipointShape([{time:mainPts[0].t,price:mainPts[0].p},{time:mainPts[1].t,price:mainPts[1].p}],
      {shape:'trend_line', overrides:{linecolor:'#2962ff', linewidth:2, extendRight:true}});
  } catch(e){} }
  // next-direction projection arrow
  const nextUp = dir==='uptrend' ? true : (dir==='downtrend' ? false : (bars[bars.length-1][4]>=bars[0][4]));
  const lastT=bars[bars.length-1][0], dt=(lastT-bars[0][0])/Math.max(1,bars.length-1);
  const projT=lastT + dt*Math.max(8, Math.floor(bars.length*0.12));
  const pNow=bars[bars.length-1][4], mv=(maxP-minP)*0.25;
  const projP = nextUp ? pNow+mv : pNow-mv, col = nextUp?'#089981':'#f23645';
  try { ch.createMultipointShape([{time:lastT,price:pNow},{time:projT,price:projP}],
        {shape:'arrow', overrides:{linecolor:col, linewidth:3}});
  } catch(e){ try { ch.createMultipointShape([{time:lastT,price:pNow},{time:projT,price:projP}],
        {shape:'trend_line', overrides:{linecolor:col, linewidth:3}}); } catch(e2){} }
  // zoom the view to the analyzed window so the structure + arrow are visible
  try { const ts=ch.getTimeScale();
    ts.setBarSpacing(Math.max(4, ts.width()/135));   // ~130 recent bars fill the width
    ts.setRightOffset(28);                           // leave room for the projection
    ts.scrollToRealtime();
  } catch(e){}
  return {ok:true, dir:dir, nextDir: nextUp?'up':'down', pivots:last.length,
          labels:last.map((p,k)=>L[k]+'='+p.type+p.p)};
}"""

# Support/Resistance zones (Magic-Line / SNR): from the last ~120 bars, draw a
# resistance band (high WICK -> high BODY) and a support band (low WICK -> low BODY).
_JS_SR = r"""() => {
  const ch = window.TradingViewApi.activeChart();
  const sd = ch.getSeries().data();
  const bars = [];
  try { sd.each(function(idx, item){ if (item && item.length >= 5) bars.push(item); }); } catch(e){}
  bars.sort((x,y)=>x[0]-y[0]);
  if (bars.length < 20) return {ok:false, err:'not enough bars ('+bars.length+')'};
  const win = bars.slice(-Math.min(120, bars.length));
  let resTop=-1e18,resBot=-1e18,supBot=1e18,supTop=1e18;
  for(const b of win){ const hi=b[2],lo=b[3],bt=Math.max(b[1],b[4]),bb=Math.min(b[1],b[4]);
    if(hi>resTop)resTop=hi; if(bt>resBot)resBot=bt; if(lo<supBot)supBot=lo; if(bb<supTop)supTop=bb; }
  const tL=win[0][0], tR=win[win.length-1][0];
  try {
    ch.createMultipointShape([{time:tL,price:resTop},{time:tR,price:resBot}],
      {shape:'rectangle', overrides:{linecolor:'#ef5350', backgroundColor:'rgba(239,83,80,0.18)', color:'rgba(239,83,80,0.18)', fillBackground:true, transparency:80}});
    ch.createMultipointShape([{time:tL,price:supTop},{time:tR,price:supBot}],
      {shape:'rectangle', overrides:{linecolor:'#26a69a', backgroundColor:'rgba(38,166,154,0.18)', color:'rgba(38,166,154,0.18)', fillBackground:true, transparency:80}});
  } catch(e){ return {ok:false, err:'draw failed: '+e}; }
  return {ok:true, resTop:resTop, resBot:resBot, supTop:supTop, supBot:supBot};
}"""


# ── persistent session (async Playwright in its own thread) ─────────────────
class _TVSession:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None
        self._browser = None

    # -- thread / loop plumbing --
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="TVSession")
        self._thread.start()
        self._ready.wait(timeout=20)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_init())
        self._ready.set()
        self._loop.run_forever()

    async def _async_init(self):
        self._pw = await async_playwright().start()

    def run(self, coro, timeout: int = 60) -> str:
        if not self._loop:
            raise RuntimeError("TV session not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    # -- browser (ATTACH to the user's clean Chrome via CDP) --
    async def _connect_or_launch(self):
        try:
            return await self._pw.chromium.connect_over_cdp(_CDP_URL)
        except Exception:
            pass
        # not running — auto-launch the dedicated debug Chrome, then retry connect
        if not _launch_debug_chrome():
            raise RuntimeError("Chrome topilmadi — TradingView'ni ocholmadim.")
        for _ in range(30):                       # wait up to ~30 s for it to come up
            await asyncio.sleep(1)
            try:
                return await self._pw.chromium.connect_over_cdp(_CDP_URL)
            except Exception:
                continue
        raise RuntimeError("TradingView Chrome ishga tushmadi — tv_chrome.bat ni qo'lda oching.")

    async def _ensure_page(self) -> Page:
        # reconnect if the user's Chrome window was closed
        if self._browser is not None and not self._browser.is_connected():
            self._ctx = self._page = self._browser = None
        if self._ctx is None:
            self._browser = await self._connect_or_launch()
            self._ctx = (self._browser.contexts[0] if self._browser.contexts
                         else await self._browser.new_context())
            self._page = None
        # (Re)pick a page only when we don't already hold a live one — this keeps
        # the "new tab per analysis" tab sticky across follow-up actions (indicator,
        # draw, remove) instead of jumping back to an older chart tab.
        if self._page is None or self._page.is_closed():
            pages = [p for p in self._ctx.pages if not p.is_closed()]
            self._page = (next((p for p in pages if "tradingview.com" in (p.url or "")), None)
                          or (pages[-1] if pages else await self._ctx.new_page()))
            # NEVER leave the user staring at a blank tab ("opened a blank screen,
            # nothing happened"): send any non-TradingView tab to the default chart.
            if "tradingview.com" not in (self._page.url or ""):
                try:
                    await self._page.goto(
                        "https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD",
                        wait_until="domcontentloaded", timeout=30000)
                    await self._wait_api()
                    await self._dismiss_popups()
                except Exception:
                    pass
        return self._page

    async def _read(self, sel: str) -> str:
        try:
            el = self._page.locator(sel).first
            if await el.count() > 0:
                return ((await el.inner_text(timeout=1500)) or "").strip().replace("\n", " ")
        except Exception:
            pass
        return ""

    async def _dismiss_popups(self):
        """Clear TradingView's first-run onboarding tooltips / promo modals that
        otherwise sit on top of the chart and intercept clicks + drawing."""
        page = self._page
        for label in ("Got it!", "Got it", "Skip", "Maybe later", "No thanks", "Dismiss"):
            try:
                btn = page.get_by_role("button", name=label, exact=False)
                for i in range(min(await btn.count(), 3)):
                    try:
                        await btn.nth(i).click(timeout=1000)
                        await asyncio.sleep(0.25)
                    except Exception:
                        pass
            except Exception:
                pass
        try:
            close = page.locator('button[data-name="close"], [aria-label*="Close" i]')
            if await close.count() > 0:
                await close.first.click(timeout=800)
        except Exception:
            pass
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

    _DLG = '[data-name="indicators-dialog"], div[role="dialog"]'

    async def _close_dialog(self):
        """Close the Indicators dialog — it stays open after adding and then
        intercepts chart/toolbar clicks.  Its X has no stable selector and Escape
        doesn't reach it, so click the X by position (always the dialog's
        top-right corner)."""
        page = self._page
        try:
            for _ in range(3):
                dlg = page.locator('[data-name="indicators-dialog"]').first
                if await dlg.count() == 0:
                    dlg = page.locator('div[role="dialog"]').first
                    if await dlg.count() == 0:
                        return
                box = await dlg.bounding_box()
                if box:
                    await page.mouse.click(box["x"] + box["width"] - 22, box["y"] + 26)
                    await asyncio.sleep(0.5)
                else:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.4)
                if await page.locator(self._DLG).count() == 0:
                    return
        except Exception:
            pass

    # -- actions --
    async def _wait_api(self) -> bool:
        """Wait until the charting JS API + bar data are ready on the page."""
        js = ("() => { try { const c = window.TradingViewApi"
              " && window.TradingViewApi.activeChart && window.TradingViewApi.activeChart();"
              " return !!(c && c.getSeries && c.getSeries().data"
              " && c.getSeries().data().size && c.getSeries().data().size() > 20);"
              " } catch(e){ return false; } }")
        for _ in range(45):                       # ~27 s max
            try:
                if await self._page.evaluate(js):
                    await asyncio.sleep(0.4)
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.6)
        return False

    async def open(self, symbol: str, interval: str | None = None,
                   new_tab: bool = True) -> str:
        await self._ensure_page()
        sym = _norm_symbol(symbol)
        url = f"https://www.tradingview.com/chart/?symbol={quote(sym)}"
        if interval:
            url += f"&interval={_norm_interval(interval)}"
        # New tab per analysis so earlier charts/analyses are preserved (user's hint).
        if new_tab and self._ctx is not None:
            self._page = await self._ctx.new_page()
        page = self._page
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        await self._wait_api()
        await self._dismiss_popups()
        title = await page.title()
        return f"Opened {sym} on TradingView ({title})."

    async def analyze(self, strategy: str) -> str:
        """Read the chart's OHLC, compute the strategy's exact points, and draw."""
        page = await self._ensure_page()
        if not await self._wait_api():
            return "Chart data is still loading — try again in a moment."
        st = (strategy or "trend").lower().strip()
        want_sr    = any(w in st for w in ("sr", "support", "resist", "zone", "snr", "magic", "both", "all"))
        want_trend = any(w in st for w in ("trend", "line", "classic", "structure", "swing", "both", "all"))
        if not want_sr and not want_trend:
            want_trend = True
        out = []
        if want_sr:                              # draw zones first (no zoom)
            try:
                r = await page.evaluate(_JS_SR)
                out.append(f"S/R zones — support {r['supBot']}–{r['supTop']}, resistance "
                           f"{r['resBot']}–{r['resTop']}" if r and r.get("ok")
                           else f"S/R failed ({(r or {}).get('err', '?')})")
            except Exception as e:
                out.append(f"S/R error: {e}")
        if want_trend:                           # trend structure last (it zooms the view)
            try:
                r = await page.evaluate(_JS_TRENDLINE)
                if r and r.get("ok"):
                    end = chr(64 + int(r.get("pivots", 1)))
                    out.append(f"trend structure {r['dir']} (swings A–{end}), next likely {r['nextDir']}")
                else:
                    out.append(f"trend failed ({(r or {}).get('err', '?')})")
            except Exception as e:
                out.append(f"trend error: {e}")
        return " | ".join(out) + ". (Structure read — not financial advice.)"

    async def set_timeframe(self, value: str) -> str:
        page = await self._ensure_page()
        iv = _norm_interval(value)
        # mid-session: TradingView accepts typing the interval then Enter
        try:
            await page.keyboard.press(iv if iv.isalpha() else iv)  # focus may matter; URL is the fallback
        except Exception:
            pass
        # reliable path: re-navigate keeping the current symbol
        cur = await self._read("#header-toolbar-symbol-search") or "OANDA:XAUUSD"
        try:
            await page.goto(
                f"https://www.tradingview.com/chart/?symbol={quote(cur)}&interval={iv}",
                wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(4)
        return f"Timeframe set to {await self._read('#header-toolbar-intervals') or value}."

    async def add_indicator(self, name: str) -> str:
        page = await self._ensure_page()
        canon = _IND_NAMES.get((name or "").lower().strip(), name)
        # FAST + RELIABLE path: add the built-in study via the charting API — one
        # call, no toolbar dialog / promo-popup / close-X fragility (verified live).
        if await self._wait_api():
            try:
                js = r"""(nm) => { try {
                  window.TradingViewApi.activeChart().createStudy(nm, false, false);
                  return true; } catch(e){ return false; } }"""
                if await page.evaluate(js, canon):
                    await asyncio.sleep(0.9)          # createStudy resolves a Promise
                    present = await page.evaluate(
                        "(nm)=>{try{return (window.TradingViewApi.activeChart().getAllStudies()||[])"
                        ".some(function(s){return (s.name||'').toLowerCase().indexOf(nm.toLowerCase())!==-1;});}"
                        "catch(e){return false;}}", canon)
                    if present:
                        return f"Added indicator: {canon}."
            except Exception:
                pass
        # FALLBACK: the Indicators dialog (toolbar) — for names createStudy rejects
        # (e.g. community scripts not in the built-in registry).
        try:
            # '/' opens the Indicators dialog; search the canonical name and click
            # the row that MATCHES it (so we add the indicator, not an "X Strategy").
            await page.keyboard.press("/")
            await asyncio.sleep(1.4)
            await page.locator('input[placeholder*="Search" i]').first.fill(canon, timeout=5000)
            await asyncio.sleep(1.6)
            row = page.locator('[data-role="list-item"]', has_text=canon).first
            if await row.count() == 0:
                row = page.locator('[data-role="list-item"]').first
            await row.click(timeout=5000)
            await asyncio.sleep(0.5)
            await self._close_dialog()                 # the dialog stays open otherwise
            return f"Added indicator: {canon}."
        except Exception as e:
            return f"Could not add indicator '{name}': {e}"

    async def remove_indicator(self, name: str) -> str:
        """Remove a study from the chart by name (e.g. 'RSI'), or all of them with
        name='all'.  Uses the charting API getAllStudies()/removeEntity() — the
        same family as removeAllShapes used by clear()."""
        page = await self._ensure_page()
        if not await self._wait_api():
            return "Chart data is still loading — try again in a moment."
        canon = _IND_NAMES.get((name or "").lower().strip(), name or "")
        js = r"""(target) => {
          const ch = window.TradingViewApi.activeChart();
          let studies = [];
          try { studies = ch.getAllStudies() || []; }
          catch(e){ return {ok:false, err:'getAllStudies: '+e}; }
          const present = studies.map(function(s){ return s.name; });
          const t = (target||'').toLowerCase().trim();
          const all = !t || t==='all' || t==='hammasi' || t==='barcha';
          const hits = all ? studies : studies.filter(function(s){
            return (s.name||'').toLowerCase().indexOf(t) !== -1; });
          let n = 0;
          hits.forEach(function(s){ try { ch.removeEntity(s.id); n++; } catch(e){} });
          return {ok:true, removed:n, names:hits.map(function(s){return s.name;}), present:present};
        }"""
        try:
            r = await page.evaluate(js, canon)
            # if the canonical title didn't match a study, retry with the short alias
            if r and r.get("ok") and not r.get("removed") and name and canon != name:
                r = await page.evaluate(js, name)
            if not (r and r.get("ok")):
                return f"Could not remove '{name}': {(r or {}).get('err', '?')}"
            if r.get("removed"):
                return f"Removed indicator: {', '.join(r.get('names') or [name])}."
            present = ", ".join(r.get("present") or []) or "none"
            return f"No '{name}' indicator on the chart (present: {present})."
        except Exception as e:
            return f"Could not remove indicator '{name}': {e}"

    async def _chart_box(self):
        for sel in ("table.chart-markup-table", "canvas"):
            el = self._page.locator(sel).first
            if await el.count() > 0:
                box = await el.bounding_box()
                if box and box["width"] > 300:
                    return box
        return None

    async def draw(self, tool: str) -> str:
        page = await self._ensure_page()
        await self._close_dialog()      # make sure no dialog is intercepting clicks
        t = (tool or "trend").lower().strip()
        # map to the left toolbar's aria-label (verified) — group buttons open a
        # submenu we then pick from (horizontal/vertical live under "Trend tools").
        group = {
            "trend": "Trendline", "trendline": "Trendline", "line": "Trendline",
            "fib": "Fib retracement", "fibonacci": "Fib retracement", "fibo": "Fib retracement",
            "text": "Text", "brush": "Brush",
            "horizontal": "Trend tools", "level": "Trend tools",
            "support": "Trend tools", "resistance": "Trend tools",
            "vertical": "Trend tools", "vline": "Trend tools",
        }.get(t, "Trendline")
        submenu = {"horizontal": "Horizontal Line", "level": "Horizontal Line",
                   "support": "Horizontal Line", "resistance": "Horizontal Line",
                   "vertical": "Vertical Line", "vline": "Vertical Line"}.get(t)
        single_click = t in ("horizontal", "level", "support", "resistance", "vertical", "vline", "text")
        try:
            await page.locator(f'button[aria-label="{group}"]').first.click(timeout=4000)
            await asyncio.sleep(0.4)
            if submenu:
                try:
                    await page.get_by_text(submenu, exact=False).first.click(timeout=2500)
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
            box = await self._chart_box()
            if not box:
                return f"Selected the {tool} tool (couldn't find the chart area to place it)."
            if single_click:
                await page.mouse.click(box["x"] + box["width"] * 0.60,
                                       box["y"] + box["height"] * 0.50)
            else:
                x0 = box["x"] + box["width"] * 0.40; y0 = box["y"] + box["height"] * 0.62
                x1 = box["x"] + box["width"] * 0.74; y1 = box["y"] + box["height"] * 0.38
                # trend/fib are TWO-CLICK tools: click anchor 1, then click anchor 2
                # to COMMIT. A press-drag only sets the 1st point — the 2nd never
                # lands, so the line just rubber-bands after the cursor (looks drawn
                # in a screenshot but isn't finished).
                await page.mouse.move(x0, y0)
                await page.mouse.click(x0, y0)
                await asyncio.sleep(0.45)
                await page.mouse.move(x1, y1, steps=8)
                await asyncio.sleep(0.15)
                await page.mouse.click(x1, y1)
            # TradingView returns to the crosshair on its own once a drawing
            # completes, so no manual deselect is needed (clicking 'Cross' just
            # opened its cursor-type dropdown; Escape would delete the drawing).
            await asyncio.sleep(0.4)
            return f"Drew a {tool} on the chart."
        except Exception as e:
            return f"Could not draw {tool}: {e}"

    async def clear(self) -> str:
        page = await self._ensure_page()
        js = ("() => { const ch=window.TradingViewApi.activeChart();"
              " try { ch.removeAllShapes(); return 'all'; } catch(e){}"
              " try { ch.getAllShapes().forEach(function(s){ try{ch.removeEntity(s.id);}catch(e){} }); return 'iter'; }"
              " catch(e){ return 'err:'+e; } }")
        try:
            r = await page.evaluate(js)
            return f"Cleared the chart's drawings ({r})."
        except Exception as e:
            return f"Clear failed: {e}"

    async def shot(self, path: str) -> str:
        page = await self._ensure_page()
        try:
            await page.screenshot(path=path, full_page=False)
            return f"screenshot saved: {path}"
        except Exception as e:
            return f"screenshot error: {e}"

    async def read_state(self) -> str:
        await self._ensure_page()
        sym = await self._read("#header-toolbar-symbol-search")
        iv = await self._read("#header-toolbar-intervals")
        title = await self._page.title()
        return f"{sym or '?'} · {iv or '?'} · {title}"


_session: _TVSession | None = None


def _get_session() -> _TVSession:
    global _session
    if _session is None:
        _session = _TVSession()
        _session.start()
    return _session


def tradingview_web(parameters: dict = None, response=None, player=None,
                    session_memory=None, speak=None) -> str:
    p = parameters or {}
    action = (p.get("action") or "open").lower().strip()
    if player:
        try: player.write_log(f"[tv_web] {action} {p.get('symbol') or p.get('tool') or ''}")
        except Exception: pass
    try:
        s = _get_session()
        if action == "analyze":
            # open the chart in a NEW TAB (keeps prior analyses) + run the strategy
            sym = p.get("symbol", "")
            opened = ""
            if sym:
                opened = s.run(s.open(sym, p.get("value") or p.get("interval"), True), timeout=115) + " "
            return opened + s.run(s.analyze(p.get("strategy") or p.get("tool") or "trend"), timeout=75)
        if action == "open":
            return s.run(s.open(p.get("symbol", ""), p.get("value") or p.get("interval")), timeout=105)
        if action in ("timeframe", "interval"):
            return s.run(s.set_timeframe(p.get("value", "1h")), timeout=50)
        if action == "indicator":
            return s.run(s.add_indicator(p.get("name", "RSI")), timeout=40)
        if action in ("remove_indicator", "delete_indicator", "remove_study"):
            return s.run(s.remove_indicator(p.get("name", "")), timeout=40)
        if action == "draw":
            return s.run(s.draw(p.get("tool", "trend")), timeout=40)
        if action in ("clear", "clear_drawings", "clean"):
            return s.run(s.clear(), timeout=25)
        if action in ("read", "state"):
            return s.run(s.read_state(), timeout=20)
        if action in ("shot", "screenshot"):
            return s.run(s.shot(p.get("path", "tv_shot.png")), timeout=20)
        return f"Unknown TradingView action: {action}"
    except Exception as e:
        return f"TradingView error ({action}): {e}"
