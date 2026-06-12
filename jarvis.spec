# -*- mode: python ; coding: utf-8 -*-
"""
JARVIS MARK XL — PyInstaller build spec (CLOUD-ONLY).

Builds a self-contained Windows app for the all-cloud pipeline
(ElevenLabs STT  ->  OpenAI LLM  ->  Muxlisa/EdgeTTS).  The heavy local-model
stack (torch / faster-whisper / kokoro / vosk) is EXCLUDED on purpose: the
deployed config never loads it, and bundling torch alone would add ~2 GB and
routinely break the build.

Build:
    .venv\\Scripts\\python.exe -m PyInstaller jarvis.spec --noconfirm
Then `build_exe.bat` copies face.png / core/prompt.txt / config beside the exe.
Result: dist\\JARVIS\\JARVIS.exe
"""
from PyInstaller.utils.hooks import collect_submodules

# Pull in every actions/* and agent/* module — several are imported lazily
# inside functions, which static analysis would otherwise miss.
hiddenimports = []
hiddenimports += collect_submodules("actions")
hiddenimports += collect_submodules("agent")
hiddenimports += collect_submodules("core")
hiddenimports += collect_submodules("mss")
hiddenimports += [
    "pandas", "openpyxl", "yt_dlp", "pptx", "cv2", "bs4",
    "duckduckgo_search", "pyautogui", "pyperclip", "pygetwindow",
    "send2trash", "soundfile", "miniaudio", "sounddevice",
    "comtypes", "pycaw", "win10toast", "pywinauto",
]

# The local-model stack — never used by the cloud config, huge, build-breaking.
excludes = [
    "torch", "torchaudio", "torchvision",
    "transformers", "tokenizers", "ctranslate2", "av",
    "faster_whisper", "kokoro", "vosk", "onnxruntime",
    "tensorflow", "tensorflow_intel",
    "tkinter", "matplotlib", "IPython", "notebook", "pytest", "nltk",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],                       # face.png / prompt.txt / config copied beside exe
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JARVIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                  # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="JARVIS",
)
