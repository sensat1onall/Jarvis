@echo off
chcp 65001 >nul
REM ===========================================================================
REM  TradingView debug-Chrome for JARVIS — a CLEAN Chrome (no automation flags),
REM  so the login captcha is human-solvable. JARVIS attaches to it over CDP.
REM  Dedicated profile => won't touch your everyday Chrome.
REM ===========================================================================
set "PROF=%USERPROFILE%\.jarvis_profiles\tv_chrome"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" ( echo Chrome topilmadi. & pause & exit /b 1 )

echo ============================================================
echo   TradingView - JARVIS uchun Chrome (debug rejimi)
echo   1) Ochilgan oynada SIGN IN qiling (captcha bo'lsa oddiy belgilang)
echo   2) Kirgach, bu Chrome oynasini OCHIQ QOLDIRING
echo      (JARVIS shu oynaga ulanib grafikni boshqaradi)
echo ============================================================
start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%PROF%" "https://www.tradingview.com/chart/?symbol=OANDA:XAUUSD"
echo.
echo Chrome ochildi (port 9222). Login qilib, oynani ochiq qoldiring.
