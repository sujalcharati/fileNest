"""Colours that follow the Windows light/dark setting and accent colour."""
from __future__ import annotations

import winreg
from dataclasses import dataclass

from PySide6.QtGui import QColor

_DEFAULT_ACCENT = QColor("#7C6CFF")


def system_dark() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return True


def system_accent() -> QColor:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
            v = winreg.QueryValueEx(k, "AccentColor")[0]  # 0xAABBGGRR
            return QColor(v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
    except OSError:
        return QColor(_DEFAULT_ACCENT)


def _rgba(r: int, g: int, b: int, a: int) -> QColor:
    return QColor(r, g, b, a)


def _alpha(c: QColor, a: int) -> QColor:
    out = QColor(c)
    out.setAlpha(a)
    return out


def css(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"


@dataclass
class Theme:
    dark: bool
    accent: QColor
    accent_text: QColor
    tint: QColor            # painted over the acrylic backdrop
    surface: QColor         # solid background when acrylic is unavailable
    border: QColor
    divider: QColor
    text: QColor
    muted: QColor
    faint: QColor
    hover: QColor
    selected: QColor
    chip: QColor
    chip_hover: QColor
    keycap: QColor
    hl_bg: QColor
    hl_text: QColor
    scroll: QColor
    success: QColor
    warning: QColor


def build_theme() -> Theme:
    dark = system_dark()
    acc = system_accent()
    h, s, l, _ = acc.getHslF()
    if h < 0 or s < 0.15:  # grey accent -> use our own violet
        h, s, l, _ = _DEFAULT_ACCENT.getHslF()
    if dark:
        l = min(max(l, 0.64), 0.74)
        s = min(max(s, 0.55), 0.95)
    else:
        l = min(max(l, 0.42), 0.52)
        s = min(max(s, 0.55), 0.95)
    accent = QColor.fromHslF(h, s, l)
    lum = 0.2126 * accent.redF() + 0.7152 * accent.greenF() + 0.0722 * accent.blueF()
    accent_text = QColor("#111114") if lum > 0.55 else QColor("#FFFFFF")

    if dark:
        return Theme(
            dark=True, accent=accent, accent_text=accent_text,
            tint=_rgba(22, 22, 27, 150),
            surface=_rgba(28, 28, 33, 252),
            border=_rgba(255, 255, 255, 26),
            divider=_rgba(255, 255, 255, 18),
            text=QColor("#F4F4F7"),
            muted=_rgba(235, 235, 245, 150),
            faint=_rgba(235, 235, 245, 92),
            hover=_rgba(255, 255, 255, 12),
            selected=_alpha(accent, 52),
            chip=_rgba(255, 255, 255, 13),
            chip_hover=_rgba(255, 255, 255, 26),
            keycap=_rgba(255, 255, 255, 18),
            hl_bg=_alpha(accent, 70),
            hl_text=QColor.fromHslF(h, min(s, 0.9), 0.86),
            scroll=_rgba(255, 255, 255, 46),
            success=QColor("#3DD68C"),
            warning=QColor("#F5B53D"),
        )
    return Theme(
        dark=False, accent=accent, accent_text=accent_text,
        tint=_rgba(250, 250, 252, 165),
        surface=_rgba(250, 250, 252, 253),
        border=_rgba(0, 0, 0, 22),
        divider=_rgba(0, 0, 0, 15),
        text=QColor("#17171C"),
        muted=_rgba(20, 20, 30, 150),
        faint=_rgba(20, 20, 30, 100),
        hover=_rgba(0, 0, 0, 10),
        selected=_alpha(accent, 34),
        chip=_rgba(0, 0, 0, 9),
        chip_hover=_rgba(0, 0, 0, 18),
        keycap=_rgba(0, 0, 0, 10),
        hl_bg=_alpha(accent, 48),
        hl_text=QColor.fromHslF(h, min(s, 0.9), 0.32),
        scroll=_rgba(0, 0, 0, 50),
        success=QColor("#1E9E62"),
        warning=QColor("#C98A12"),
    )
