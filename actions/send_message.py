import json
import subprocess
import sys
import time
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.06
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_os() -> str:
    try:
        cfg = json.loads(
            (_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
        return cfg.get("os_system", "windows").lower()
    except Exception:
        return "windows"


def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


def _paste_text(text: str) -> None:
    _require_pyautogui()

    os_name = _get_os()
    paste_hotkey = ("command", "v") if os_name == "mac" else ("ctrl", "v")

    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey(*paste_hotkey)
        time.sleep(0.1)
    else:
        pyautogui.write(text, interval=0.03)


def _clear_and_paste(text: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    select_all = ("command", "a") if os_name == "mac" else ("ctrl", "a")
    pyautogui.hotkey(*select_all)
    time.sleep(0.1)
    pyautogui.press("delete")
    time.sleep(0.1)
    _paste_text(text)

def _focus_existing(app_name: str) -> bool:
    """If a window for this app is already open, bring it to the front (fast) and
    return True — so a follow-up 'text X' doesn't relaunch an app that's already
    running (and is much faster than the Start-menu launch dance)."""
    try:
        import pygetwindow as gw
    except Exception:
        return False
    name = app_name.lower().strip()
    try:
        for w in gw.getAllWindows():
            title = (w.title or "").strip()
            if not title or name not in title.lower():
                continue
            try:
                if getattr(w, "isMinimized", False):
                    w.restore()
                w.activate()
                time.sleep(0.4)
                return True
            except Exception:
                try:
                    esc = title.replace("'", "''")
                    subprocess.run(
                        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                         f"(New-Object -ComObject WScript.Shell).AppActivate('{esc}')"],
                        capture_output=True, timeout=4,
                    )
                    time.sleep(0.4)
                    return True
                except Exception:
                    return False
    except Exception:
        return False
    return False


def _open_app(app_name: str) -> bool:
    _require_pyautogui()
    os_name = _get_os()

    try:
        if os_name == "windows":
            # Fast path: if the app is already open, just focus it (no relaunch).
            if _focus_existing(app_name):
                return True
            pyautogui.press("win")
            time.sleep(0.5)
            _paste_text(app_name)
            time.sleep(0.6)
            pyautogui.press("enter")
            time.sleep(2.5)
            return True

        elif os_name == "mac":
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ["open", "-a", f"{app_name}.app"],
                    capture_output=True, text=True, timeout=10,
                )
            time.sleep(2.5)
            return result.returncode == 0

        else: 
            launched = False
            for launcher in [
                ["gtk-launch", app_name.lower()],
                [app_name.lower()],
            ]:
                try:
                    subprocess.Popen(
                        launcher,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    launched = True
                    break
                except FileNotFoundError:
                    continue
            time.sleep(2.5)
            return launched

    except Exception as e:
        print(f"[SendMessage] ⚠️ Could not open {app_name}: {e}")
        return False


def _open_browser_url(url: str) -> bool:
    import webbrowser
    try:
        webbrowser.open(url)
        time.sleep(4.0) 
        return True
    except Exception as e:
        print(f"[SendMessage] ⚠️ Could not open browser: {e}")
        return False

def _search_in_app(query: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    search_hotkey = ("command", "f") if os_name == "mac" else ("ctrl", "f")

    pyautogui.hotkey(*search_hotkey)
    time.sleep(0.5)
    _clear_and_paste(query)
    time.sleep(1.0)

def _desktop_send(app_name: str, receiver: str, message: str) -> str:
    if not _open_app(app_name):
        return f"Could not open {app_name}."

    time.sleep(1.0)
    _search_in_app(receiver)
    pyautogui.press("enter")
    time.sleep(0.8)

    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)
    return f"Message sent to {receiver} via {app_name}."

def _send_whatsapp(receiver: str, message: str) -> str:
    return _desktop_send("WhatsApp", receiver, message)

def _send_telegram(receiver: str, message: str) -> str:
    return _desktop_send("Telegram", receiver, message)

def _send_signal(receiver: str, message: str) -> str:
    return _desktop_send("Signal", receiver, message)


def _send_discord(receiver: str, message: str) -> str:
    return _desktop_send("Discord", receiver, message)


def _send_instagram(receiver: str, message: str) -> str:
    _require_pyautogui()

    if not _open_browser_url("https://www.instagram.com/direct/new/"):
        return "Could not open Instagram in browser."

    _paste_text(receiver)
    time.sleep(1.5)

    pyautogui.press("down")
    time.sleep(0.3)
    pyautogui.press("enter")   
    time.sleep(0.4)

    for _ in range(4):
        pyautogui.press("tab")
        time.sleep(0.15)
    pyautogui.press("enter")
    time.sleep(2.0)

    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)

    return f"Message sent to {receiver} via Instagram."


def _send_messenger(receiver: str, message: str) -> str:
    _require_pyautogui()

    if not _open_browser_url("https://www.messenger.com/"):
        return "Could not open Messenger in browser."


    _search_in_app(receiver)
    time.sleep(0.5)
    pyautogui.press("down")
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(1.0)

    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)

    return f"Message sent to {receiver} via Messenger."

_PLATFORM_MAP = [
    ({"whatsapp", "wp", "wapp"},              _send_whatsapp),
    ({"telegram", "tg"},                      _send_telegram),
    ({"instagram", "ig", "insta"},            _send_instagram),
    ({"signal"},                               _send_signal),
    ({"discord"},                              _send_discord),
    ({"messenger", "facebook", "fb"},         _send_messenger),
]


def _resolve_platform(platform_str: str):
    key = platform_str.lower().strip()
    for keywords, handler in _PLATFORM_MAP:
        if any(k in key for k in keywords):
            return handler
    return lambda r, m: _desktop_send(platform_str.strip().title(), r, m)


def send_message(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params       = parameters or {}
    receiver     = params.get("receiver", "").strip()
    message_text = params.get("message_text", "").strip()
    platform     = params.get("platform", "whatsapp").strip()

    if not receiver:
        return "Please specify a recipient."
    if not message_text:
        return "Please specify the message content."
    if not _PYAUTOGUI:
        return "PyAutoGUI is not installed — cannot control the desktop."

    preview = message_text[:50] + ("…" if len(message_text) > 50 else "")
    print(f"[SendMessage] 📨 {platform} → {receiver}: {preview}")
    if player:
        player.write_log(f"[msg] {platform} → {receiver}")

    try:
        handler = _resolve_platform(platform)
        result  = handler(receiver, message_text)
    except Exception as e:
        result = f"Could not send message: {e}"

    print(f"[SendMessage] {'✅' if 'sent' in result.lower() else '❌'} {result}")
    if player:
        player.write_log(f"[msg] {result}")

    return result


# ---------------------------------------------------------------------------
# Reading incoming messages (vision) — "what did X say?"
# ---------------------------------------------------------------------------

_APP_NAMES = {
    "telegram": "Telegram", "tg": "Telegram",
    "whatsapp": "WhatsApp", "wp": "WhatsApp", "wapp": "WhatsApp",
    "signal":   "Signal",   "discord": "Discord",
}


def _app_name_for(platform: str) -> str:
    key = (platform or "telegram").lower().strip()
    for k, v in _APP_NAMES.items():
        if k in key:
            return v
    return (platform or "").strip().title() or "Telegram"


def _vision_read_messages(app: str, sender: str) -> str:
    try:
        import io, base64
        from core.llm_client import call_vision
        from actions.computer_control import capture_window
        cap = capture_window(app)
        if cap:
            b64 = cap[0]                          # cropped to just the chat window
        else:
            img = pyautogui.screenshot()
            buf = io.BytesIO(); img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        who = f"from {sender}" if sender else "from the other person"
        prompt = (
            f"This is a screenshot of the {app} chat app. "
            f"Read the most RECENT incoming message(s) {who} — the bubbles aligned to the "
            f"LEFT (the other person's messages), NOT the user's own messages on the right. "
            f"Return only the latest 1-3 message texts, verbatim, oldest first. "
            f"If no messages are visible, reply exactly: NO_MESSAGES"
        )
        text = call_vision(b64, prompt, mime="image/png", timeout=40)
        if not text or "NO_MESSAGES" in text.upper():
            return "I couldn't read any messages on the screen."
        return f"Latest message {who}: {text.strip()}"
    except Exception as e:
        return f"Could not read the messages: {e}"


def read_messages(parameters: dict = None, response=None, player=None,
                  session_memory=None, speak=None) -> str:
    """Read the latest incoming message(s) in a chat app and return them so the
    LLM can tell the user (in Uzbek) what was said.  Reads the CURRENTLY OPEN
    chat — which is the person just texted in the common 'X replied' case."""
    if not _PYAUTOGUI:
        return "PyAutoGUI is not installed — cannot read the screen."
    p        = parameters or {}
    platform = (p.get("platform") or "telegram").strip()
    sender   = (p.get("sender") or p.get("receiver") or "").strip()
    app      = _app_name_for(platform)

    if player:
        player.write_log(f"[read_msg] {app} {sender}")

    # Bring the app to the front (open it only if it isn't already running).
    if not _focus_existing(app):
        if not _open_app(app):
            return f"Could not open {app} to read the messages."
        time.sleep(1.2)
    time.sleep(0.6)

    return _vision_read_messages(app, sender)