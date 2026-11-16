"""Windows-specific bits: acrylic backdrop, global hotkey, focus, start-with-Windows."""
from __future__ import annotations

import ctypes
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
_MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "`": 0xC0, "backquote": 0xC0}

# DWM window attributes
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_ROUND = 2
DWMSBT_TRANSIENTWINDOW = 3  # acrylic


class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


def windows_build() -> int:
    return sys.getwindowsversion().build


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    v = ctypes.c_int(value)
    return dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0


def apply_window_effects(hwnd: int, dark: bool, acrylic: bool) -> tuple[bool, bool]:
    """Returns (rounded corners by DWM, acrylic backdrop active)."""
    build = windows_build()
    _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
    rounded = build >= 22000 and _set_attr(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    if not acrylic or build < 22621:
        return rounded, False
    m = MARGINS(-1, -1, -1, -1)
    dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(m))
    return rounded, _set_attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_TRANSIENTWINDOW)


# --------------------------------------------------------------------------- hotkey

def parse_hotkey(spec: str) -> tuple[int, int]:
    mods, vk = 0, None
    for part in spec.replace(" ", "").split("+"):
        k = part.lower()
        if k in _MODS:
            mods |= _MODS[k]
        elif k in _KEYS:
            vk = _KEYS[k]
        elif len(k) == 1 and k.isalnum():
            vk = ord(k.upper())
        elif k.startswith("f") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
            vk = 0x70 + int(k[1:]) - 1
        else:
            raise ValueError(f"unknown key {part!r} in hotkey {spec!r}")
    if vk is None:
        raise ValueError(f"hotkey {spec!r} has no main key")
    return mods, vk


def register_hotkey(hwnd: int, hk_id: int, spec: str) -> bool:
    try:
        mods, vk = parse_hotkey(spec)
    except ValueError:
        return False
    return bool(user32.RegisterHotKey(hwnd, hk_id, mods | MOD_NOREPEAT, vk))


def unregister_hotkey(hwnd: int, hk_id: int) -> None:
    user32.UnregisterHotKey(hwnd, hk_id)


def force_foreground(hwnd: int) -> None:
    if user32.SetForegroundWindow(hwnd) and user32.GetForegroundWindow() == hwnd:
        return
    # Windows sometimes refuses; a synthetic Alt tap unlocks SetForegroundWindow.
    VK_MENU, KEYUP = 0x12, 0x2
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYUP, 0)
    user32.SetForegroundWindow(hwnd)


def allow_any_foreground() -> None:
    user32.AllowSetForegroundWindow(-1)


def set_app_id(app_id: str) -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass


# --------------------------------------------------------------------------- start with Windows

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "FileNest"


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --background'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    if pyw.exists():
        exe = pyw
    script = Path(__file__).resolve().parent.parent / "FileNest.pyw"
    return f'"{exe}" "{script}" --background'


def is_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _RUN_NAME)
            return True
    except OSError:
        return False


def set_startup(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, _RUN_NAME)
            except FileNotFoundError:
                pass
