"""Paths and user settings (stored in %LOCALAPPDATA%\\FileNest\\settings.json)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

APP_NAME = "FileNest"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "index.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_PATH = DATA_DIR / "filenest.log"

DEFAULT_SETTINGS: dict = {
    # Global shortcut that opens the search bar. First one that Windows accepts wins.
    "hotkeys": ["Alt+Space", "Ctrl+Alt+Space", "Ctrl+Shift+Space"],
    # Drives to index, e.g. ["C:\\", "D:\\"]. Empty = all fixed (internal) drives.
    "drives": [],
    # Extra folders to index (e.g. on a USB or network drive).
    "extra_folders": [],
    # Folder names skipped wherever they appear.
    "exclude_folder_names": [
        "$Recycle.Bin", "System Volume Information", "$WinREAgent", "$Windows.~BT",
        "$Windows.~WS", "$SysReset", "Config.Msi", "MSOCache",
        "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
        ".cache", ".gradle", ".m2", ".npm", ".nuget", ".tox", ".mypy_cache",
        ".pytest_cache", "site-packages", "WindowsApps",
    ],
    # Full paths skipped (environment variables like %LOCALAPPDATA% are allowed).
    "exclude_paths": [
        "%SystemRoot%",
        "%ProgramFiles%",
        "%ProgramFiles(x86)%",
        "%ProgramData%",
        "%SystemDrive%\\Recovery",
        "%SystemDrive%\\$GetCurrent",
        "%SystemDrive%\\PerfLogs",
        "%LOCALAPPDATA%\\Temp",
        "%LOCALAPPDATA%\\Packages",
        "%LOCALAPPDATA%\\Microsoft",
        "%LOCALAPPDATA%\\Google",
        "%LOCALAPPDATA%\\Mozilla",
        "%LOCALAPPDATA%\\BraveSoftware",
        "%LOCALAPPDATA%\\CrashDumps",
        "%LOCALAPPDATA%\\D3DSCache",
        "%LOCALAPPDATA%\\pip",
        "%LOCALAPPDATA%\\npm-cache",
        "%LOCALAPPDATA%\\FileNest",
        "%APPDATA%\\Microsoft",
        "%APPDATA%\\Code",
        "%APPDATA%\\discord",
        "%APPDATA%\\Spotify",
    ],
    # Full re-scan this often (live changes are tracked in between).
    "rescan_every_hours": 6,
    # Frosted-glass window background (Windows 11 22H2+).
    "acrylic": True,
}


def load_settings() -> dict:
    data: dict = {}
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logging.exception("settings.json is invalid, using defaults")
            data = {}
    merged = {**DEFAULT_SETTINGS, **data}
    if merged != data:
        try:
            SETTINGS_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        except OSError:
            logging.exception("could not write settings.json")
    return merged
