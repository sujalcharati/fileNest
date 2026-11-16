"""The search window: a frosted command-palette style popup."""
from __future__ import annotations

import os
import subprocess
import time

from PySide6.QtCore import (QAbstractListModel, QEasingCurve, QEvent, QModelIndex, QPoint, QPointF,
                            QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication,
                           QPainter, QPainterPath, QPalette, QPen)
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QGraphicsOpacityEffect,
                               QHBoxLayout, QLabel, QLineEdit, QListView, QMenu, QPushButton,
                               QStackedLayout, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from . import winfx
from .filetypes import FILTERS, category_for
from .indexer import Index, Result
from .theme import Theme, css

HOTKEY_ID = 0xF11E

# --------------------------------------------------------------------------- fonts & helpers

_FAMILIES: set[str] | None = None


def ui_font(px: float, weight: QFont.Weight = QFont.Weight.Normal, display: bool = False) -> QFont:
    global _FAMILIES
    if _FAMILIES is None:
        _FAMILIES = set(QFontDatabase.families())
    wanted = "Segoe UI Variable Display" if display else "Segoe UI Variable Text"
    for name in (wanted, "Segoe UI Variable", "Segoe UI"):
        if name in _FAMILIES:
            break
    f = QFont(name)
    f.setPixelSize(int(px))
    f.setWeight(weight)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def rel_time(ts: float | None) -> str:
    if not ts:
        return ""
    d = time.time() - ts
    if d < 60:
        return "Just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} hr ago"
    if d < 172800:
        return "Yesterday"
    if d < 7 * 86400:
        return f"{int(d // 86400)} days ago"
    t = time.localtime(ts)
    if t.tm_year == time.localtime().tm_year:
        return time.strftime("%d %b", t).lstrip("0")
    return time.strftime("%d %b %Y", t).lstrip("0")


def human_size(n: int | None) -> str:
    if n is None:
        return ""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def match_spans(text: str, terms: list[str]) -> list[tuple[int, int]]:
    low = text.lower()
    spans = []
    for t in terms:
        t = t.lower()
        if not t or "\\" in t or "/" in t:
            continue
        i = low.find(t)
        while i != -1:
            spans.append((i, i + len(t)))
            i = low.find(t, i + len(t))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    return merged


def rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def draw_folder_glyph(p: QPainter, r: QRectF, color: QColor) -> None:
    back = rounded(QRectF(r.left(), r.top(), r.width() * 0.46, r.height() * 0.42), 2.2)
    body = rounded(QRectF(r.left(), r.top() + r.height() * 0.2, r.width(), r.height() * 0.8), 2.8)
    p.fillPath(back, QColor(color).darker(125))
    p.fillPath(body, color)


def draw_badge(p: QPainter, rect: QRectF, r: Result, t: Theme, f_big: QFont, f_small: QFont) -> None:
    cat = category_for(r.ext, bool(r.is_dir))
    base = QColor(cat.color)
    bg = QColor(base)
    bg.setAlpha(48 if t.dark else 36)
    p.fillPath(rounded(rect, 10), bg)
    if r.is_dir:
        draw_folder_glyph(p, rect.adjusted(9, 10, -9, -10), base)
        return
    fg = base.lighter(140) if t.dark else base.darker(118)
    label = (r.ext or "file")[:4].upper()
    p.setFont(f_big if len(label) <= 3 else f_small)
    p.setPen(fg)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


def draw_highlighted(p: QPainter, rect: QRectF, text: str, terms: list[str], font: QFont,
                     color: QColor, hl_bg: QColor, hl_color: QColor) -> None:
    fm = QFontMetricsF(font)
    text = fm.elidedText(text, Qt.TextElideMode.ElideMiddle, rect.width())
    p.setFont(font)
    baseline = rect.top() + (rect.height() + fm.ascent() - fm.descent()) / 2
    pieces: list[tuple[str, bool]] = []
    pos = 0
    for s, e in match_spans(text, terms):
        if s > pos:
            pieces.append((text[pos:s], False))
        pieces.append((text[s:e], True))
        pos = e
    if pos < len(text):
        pieces.append((text[pos:], False))
    x = rect.left()
    for seg, hl in pieces:
        w = fm.horizontalAdvance(seg)
        if hl:
            bg = QRectF(x - 1.5, baseline - fm.ascent() - 0.5, w + 3, fm.ascent() + fm.descent() + 1)
            p.fillPath(rounded(bg, 4), hl_bg)
            p.setPen(hl_color)
        else:
            p.setPen(color)
        p.drawText(QPointF(x, baseline), seg)
        x += w


# --------------------------------------------------------------------------- model / delegate

class ResultModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.rows: list[Result] = []
        self.terms: list[str] = []

    def set_rows(self, rows: list[Result], terms: list[str]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.terms = terms
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return r
        if role == Qt.ItemDataRole.ToolTipRole:
            return r.path
        if role == Qt.ItemDataRole.DisplayRole:
            return r.name
        return None


class ResultDelegate(QStyledItemDelegate):
    ROW_H = 58

    def __init__(self, theme: Theme, model: ResultModel, parent=None):
        super().__init__(parent)
        self.t = theme
        self.model = model
        self.f_name = ui_font(14, QFont.Weight.DemiBold)
        self.f_path = ui_font(12)
        self.f_meta = ui_font(12)
        self.f_meta2 = ui_font(11)
        self.f_badge = ui_font(10.5, QFont.Weight.Bold)
        self.f_badge_small = ui_font(9, QFont.Weight.Bold)

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, p: QPainter, option, index) -> None:
        r: Result = index.data(Qt.ItemDataRole.UserRole)
        if r is None:
            return
        t = self.t
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rect = QRectF(option.rect).adjusted(8, 2, -8, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            p.fillPath(rounded(rect, 10), t.selected if selected else t.hover)
        if selected:
            p.fillPath(rounded(QRectF(rect.left() + 2, rect.center().y() - 9, 3, 18), 1.5), t.accent)

        icon = QRectF(rect.left() + 14, rect.center().y() - 18, 36, 36)
        draw_badge(p, icon, r, t, self.f_badge, self.f_badge_small)

        right_w = 96.0
        x = icon.right() + 14
        text_w = max(40.0, rect.right() - x - right_w - 18)
        draw_highlighted(p, QRectF(x, rect.top() + 8, text_w, 21), r.name, self.model.terms,
                         self.f_name, t.text, t.hl_bg, t.hl_text)

        parent = os.path.dirname(r.path)
        fm = QFontMetricsF(self.f_path)
        p.setFont(self.f_path)
        p.setPen(t.muted)
        p.drawText(QRectF(x, rect.top() + 29, text_w, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(parent, Qt.TextElideMode.ElideMiddle, text_w))

        mx = rect.right() - right_w - 12
        p.setFont(self.f_meta)
        p.setPen(t.muted)
        p.drawText(QRectF(mx, rect.top() + 8, right_w, 21),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, rel_time(r.mtime))
        p.setFont(self.f_meta2)
        p.setPen(t.faint)
        p.drawText(QRectF(mx, rect.top() + 29, right_w, 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "Folder" if r.is_dir else human_size(r.size))
        p.restore()


# --------------------------------------------------------------------------- small widgets

class SearchGlyph(QWidget):
    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.t = theme
        self.setFixedSize(24, 24)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.t.muted, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawEllipse(QPointF(10.5, 10.5), 6.5, 6.5)
        p.drawLine(QPointF(15.5, 15.5), QPointF(20, 20))


class Keycap(QWidget):
    """A small keyboard key, e.g. [Esc]."""

    def __init__(self, text: str, theme: Theme, parent=None):
        super().__init__(parent)
        self.text = text
        self.t = theme
        self.font_ = ui_font(11, QFont.Weight.DemiBold)
        w = QFontMetricsF(self.font_).horizontalAdvance(text) + 14
        self.setFixedSize(int(max(24, w)), 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.fillPath(rounded(r, 6), self.t.keycap)
        p.setPen(QPen(self.t.border, 1))
        p.drawPath(rounded(r, 6))
        p.setFont(self.font_)
        p.setPen(self.t.muted)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text)


class Divider(QWidget):
    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.t = theme
        self.setFixedHeight(1)

    def paintEvent(self, _):
        QPainter(self).fillRect(self.rect(), self.t.divider)


class EmptyState(QWidget):
    """Shown when there are no results, or while the index is being built."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.t = theme
        self.mode = "empty"
        self.title = ""
        self.subtitle = ""
        self.detail = ""
        self._angle = 0.0
        self._timer = QTimer(self, interval=16, timeout=self._tick)
        self.f_title = ui_font(16, QFont.Weight.DemiBold, display=True)
        self.f_sub = ui_font(13)
        self.f_detail = ui_font(11.5)

    def set_state(self, mode: str, title: str, subtitle: str = "", detail: str = "") -> None:
        self.mode, self.title, self.subtitle, self.detail = mode, title, subtitle, detail
        if mode == "building":
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self):
        self._angle = (self._angle + 6) % 360
        self.update()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        if self.mode == "building":
            self._timer.start()
        super().showEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        cx = self.width() / 2
        cy = self.height() / 2 - 34
        circle = QRectF(cx - 30, cy - 30, 60, 60)
        tinted = QColor(t.accent)
        tinted.setAlpha(40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tinted)
        p.drawEllipse(circle)

        if self.mode == "building":
            track = QColor(t.accent)
            track.setAlpha(60)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(track, 3))
            ring = circle.adjusted(14, 14, -14, -14)
            p.drawEllipse(ring)
            pen = QPen(t.accent, 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(ring, int(-self._angle * 16), 100 * 16)
        else:
            pen = QPen(t.accent, 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx - 3, cy - 3), 9, 9)
            p.drawLine(QPointF(cx + 3.5, cy + 3.5), QPointF(cx + 10, cy + 10))

        y = cy + 46
        p.setFont(self.f_title)
        p.setPen(t.text)
        fm = QFontMetricsF(self.f_title)
        p.drawText(QRectF(24, y, self.width() - 48, 24), Qt.AlignmentFlag.AlignCenter,
                   fm.elidedText(self.title, Qt.TextElideMode.ElideMiddle, self.width() - 48))
        if self.subtitle:
            p.setFont(self.f_sub)
            p.setPen(t.muted)
            p.drawText(QRectF(24, y + 28, self.width() - 48, 20), Qt.AlignmentFlag.AlignCenter,
                       self.subtitle)
        if self.detail:
            p.setFont(self.f_detail)
            p.setPen(t.faint)
            fmd = QFontMetricsF(self.f_detail)
            p.drawText(QRectF(40, y + 52, self.width() - 80, 18), Qt.AlignmentFlag.AlignCenter,
                       fmd.elidedText(self.detail, Qt.TextElideMode.ElideMiddle, self.width() - 80))


class Footer(QWidget):
    HINTS = [(["↵"], "Open"), (["Ctrl", "↵"], "Show in folder"), (["Ctrl", "C"], "Copy path")]

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.t = theme
        self.setFixedHeight(42)
        self.status = ""
        self.live = True
        self._flash = ""
        self._flash_timer = QTimer(self, singleShot=True, interval=1800, timeout=self._clear_flash)
        self.f = ui_font(12)
        self.f_key = ui_font(10.5, QFont.Weight.DemiBold)

    def set_status(self, text: str, live: bool) -> None:
        self.status, self.live = text, live
        self.update()

    def flash(self, text: str) -> None:
        self._flash = text
        self._flash_timer.start()
        self.update()

    def _clear_flash(self):
        self._flash = ""
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        p.fillRect(QRectF(0, 0, self.width(), 1), t.divider)
        cy = self.height() / 2 + 0.5

        # right-hand key hints (drawn right to left)
        fm = QFontMetricsF(self.f)
        fmk = QFontMetricsF(self.f_key)
        x = self.width() - 18.0
        for keys, label in reversed(self.HINTS):
            lw = fm.horizontalAdvance(label)
            x -= lw
            p.setFont(self.f)
            p.setPen(t.faint)
            p.drawText(QRectF(x, 0, lw + 2, self.height()), Qt.AlignmentFlag.AlignVCenter, label)
            x -= 7
            for k in reversed(keys):
                kw = max(20.0, fmk.horizontalAdvance(k) + 12)
                x -= kw
                r = QRectF(x, cy - 10, kw, 20)
                p.fillPath(rounded(r, 5), t.keycap)
                p.setPen(QPen(t.border, 1))
                p.drawPath(rounded(r, 5))
                p.setFont(self.f_key)
                p.setPen(t.muted)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, k)
                x -= 4
            x -= 16
        hints_left = x

        # left-hand status
        if self._flash:
            dot, text, color = t.accent, self._flash, t.text
        else:
            dot, text, color = (t.success if self.live else t.warning), self.status, t.muted
        p.setPen(Qt.PenStyle.NoPen)
        glow = QColor(dot)
        glow.setAlpha(60)
        p.setBrush(glow)
        p.drawEllipse(QPointF(22, cy), 6, 6)
        p.setBrush(dot)
        p.drawEllipse(QPointF(22, cy), 3.2, 3.2)
        p.setFont(self.f)
        p.setPen(color)
        avail = hints_left - 36
        p.drawText(QRectF(36, 0, avail, self.height()), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(text, Qt.TextElideMode.ElideRight, avail))


# --------------------------------------------------------------------------- window

class SearchWindow(QWidget):
    hotkeyPressed = Signal()

    def __init__(self, theme: Theme, index: Index, acrylic: bool = True):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.t = theme
        self.index = index
        self.filter_key = "all"
        self.pinned = False          # True = don't auto-hide when focus is lost (testing)
        self._menu_open = False
        self._build_progress: tuple[int, str] | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("FileNest")
        self.resize(800, 560)

        self._dwm_round, self._acrylic = winfx.apply_window_effects(int(self.winId()), theme.dark, acrylic)

        self._build_ui()
        self._debounce = QTimer(self, singleShot=True, interval=40, timeout=self.run_search)
        self.edit.textChanged.connect(lambda _: self._debounce.start())
        self.edit.installEventFilter(self)

    # ---- construction
    def _build_ui(self) -> None:
        t = self.t
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content = QWidget(self)
        outer.addWidget(self.content)
        self._fade = QGraphicsOpacityEffect(self.content)
        self._fade.setOpacity(1.0)
        self.content.setGraphicsEffect(self._fade)

        lay = QVBoxLayout(self.content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # search row
        row = QHBoxLayout()
        row.setContentsMargins(22, 18, 18, 12)
        row.setSpacing(14)
        row.addWidget(SearchGlyph(t))
        self.edit = QLineEdit()
        self.edit.setFont(ui_font(21, QFont.Weight.Normal, display=True))
        self.edit.setPlaceholderText("Search files and folders…")
        self.edit.setFrame(False)
        self.edit.setStyleSheet(
            f"QLineEdit{{background:transparent;border:none;padding:0;color:{css(t.text)};"
            f"selection-background-color:{css(t.hl_bg)};selection-color:{css(t.text)};}}")
        pal = self.edit.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, t.faint)
        self.edit.setPalette(pal)
        row.addWidget(self.edit, 1)
        row.addWidget(Keycap("Esc", t))
        lay.addLayout(row)

        # filter chips
        chips = QHBoxLayout()
        chips.setContentsMargins(20, 0, 20, 14)
        chips.setSpacing(6)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chips: list[QPushButton] = []
        chip_css = (
            f"QPushButton{{background:{css(t.chip)};color:{css(t.muted)};border:1px solid {css(t.border)};"
            f"border-radius:13px;padding:0 13px;}}"
            f"QPushButton:hover{{background:{css(t.chip_hover)};color:{css(t.text)};}}"
            f"QPushButton:checked{{background:{css(t.accent)};color:{css(t.accent_text)};"
            f"border:1px solid {css(t.accent)};}}")
        for i, (key, label, _) in enumerate(FILTERS):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(ui_font(12, QFont.Weight.DemiBold))
            b.setFixedHeight(26)
            b.setStyleSheet(chip_css)
            b.setProperty("filter_key", key)
            self.chip_group.addButton(b, i)
            self.chips.append(b)
            chips.addWidget(b)
        chips.addStretch(1)
        self.chips[0].setChecked(True)
        self.chip_group.idClicked.connect(self._chip_clicked)
        lay.addLayout(chips)

        lay.addWidget(Divider(t))

        # caption
        self.caption = QLabel()
        f = ui_font(11, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        self.caption.setFont(f)
        self.caption.setStyleSheet(f"color:{css(t.faint)};background:transparent;")
        self.caption.setContentsMargins(24, 12, 24, 6)
        lay.addWidget(self.caption)

        # results / empty state
        stack_host = QWidget()
        self.stack = QStackedLayout(stack_host)
        self.model = ResultModel()
        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setItemDelegate(ResultDelegate(t, self.model, self.list))
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setFrameShape(QListView.Shape.NoFrame)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.verticalScrollBar().setSingleStep(18)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.doubleClicked.connect(lambda _: self.open_current())
        self.list.setStyleSheet(
            "QListView{background:transparent;border:none;outline:none;padding:0 6px 6px 6px;}"
            "QScrollBar:vertical{background:transparent;width:12px;margin:2px 3px 6px 0;}"
            f"QScrollBar::handle:vertical{{background:{css(t.scroll)};border-radius:3px;"
            "min-height:36px;margin:0 2px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}")
        self.list.viewport().setAutoFillBackground(False)
        self.empty = EmptyState(t)
        self.stack.addWidget(self.list)
        self.stack.addWidget(self.empty)
        lay.addWidget(stack_host, 1)

        self.footer = Footer(t)
        lay.addWidget(self.footer)

    # ---- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._acrylic:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(), self.t.tint)
            return
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 0 if self._dwm_round else 12
        path = rounded(r, radius)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.fillPath(path, self.t.surface)
        if not self._dwm_round:
            p.setPen(QPen(self.t.border, 1))
            p.drawPath(path)

    # ---- show / hide
    def summon(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        w = min(800, g.width() - 40)
        h = min(560, int(g.height() * 0.72))
        self.resize(w, h)
        target = QPoint(g.x() + (g.width() - w) // 2, g.y() + int(g.height() * 0.15))
        self.move(target + QPoint(0, 12))
        self.show()
        self.raise_()
        self.activateWindow()
        winfx.force_foreground(int(self.winId()))
        self.edit.setFocus()
        self.edit.selectAll()
        self.refresh_status()
        self.run_search()

        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(220)
        self._pos_anim.setStartValue(target + QPoint(0, 12))
        self._pos_anim.setEndValue(target)
        self._pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim = QPropertyAnimation(self._fade, b"opacity", self)
        self._fade_anim.setDuration(170)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pos_anim.start()
        self._fade_anim.start()

    def toggle(self) -> None:
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.summon()

    def event(self, e):
        if e.type() == QEvent.Type.WindowDeactivate and not self.pinned:
            QTimer.singleShot(0, self._maybe_hide)
        return super().event(e)

    def _maybe_hide(self) -> None:
        if self.isVisible() and not self.isActiveWindow() and not self._menu_open:
            self.hide()

    def nativeEvent(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == winfx.WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.hotkeyPressed.emit()
                return True, 0
        return super().nativeEvent(event_type, message)

    # ---- index state
    def refresh_status(self) -> None:
        if self._build_progress is not None and not self.index.ready:
            n, _ = self._build_progress
            self.footer.set_status(f"Building your index · {n:,} items so far", live=False)
        elif self._build_progress is not None:
            self.footer.set_status(f"{self.index.count():,} items · refreshing in background", live=False)
        elif self.index.ready:
            self.footer.set_status(f"{self.index.count():,} items indexed · live", live=True)
        else:
            self.footer.set_status("No index yet", live=False)

    def set_build_progress(self, count: int, folder: str) -> None:
        self._build_progress = (count, folder)
        if self.isVisible():
            self.refresh_status()
            if not self.index.ready:
                self._show_building()

    def build_finished(self) -> None:
        self._build_progress = None
        if self.isVisible():
            self.refresh_status()
            self.run_search()

    def _show_building(self) -> None:
        n, folder = self._build_progress or (0, "")
        self.caption.setText("SETTING UP")
        self.empty.set_state("building", "Building your index…",
                             f"{n:,} files and folders found so far. This only happens once.", folder)
        self.stack.setCurrentWidget(self.empty)

    # ---- searching
    def _chip_clicked(self, i: int) -> None:
        self.filter_key = FILTERS[i][0]
        self.run_search()
        self.edit.setFocus()

    def cycle_filter(self, step: int) -> None:
        i = (self.chip_group.checkedId() + step) % len(self.chips)
        self.chips[i].setChecked(True)
        self._chip_clicked(i)

    def run_search(self) -> None:
        q = self.edit.text().strip()
        if not self.index.ready:
            if self._build_progress is not None:
                self._show_building()
            else:
                self.caption.setText("")
                self.empty.set_state("empty", "No index yet", "Use the tray icon to build one.")
                self.stack.setCurrentWidget(self.empty)
            return
        rows, total, capped = self.index.search(q, self.filter_key)
        self.model.set_rows(rows, q.split())
        label = FILTERS[self.chip_group.checkedId()][1]
        if not q:
            self.caption.setText("RECENTLY MODIFIED" if self.filter_key == "all"
                                 else f"RECENT · {label.upper()}")
        else:
            more = "+" if capped else ""
            self.caption.setText(f"BEST MATCHES · {total:,}{more}" if rows else "")
        if rows:
            self.stack.setCurrentWidget(self.list)
            self.list.setCurrentIndex(self.model.index(0))
            self.list.scrollToTop()
        else:
            if q:
                where = "" if self.filter_key == "all" else f" in {label}"
                self.empty.set_state("empty", f"No matches for “{q}”{where}",
                                     "Try fewer letters, or switch the filter with Tab.")
            else:
                self.empty.set_state("empty", "Start typing to find anything",
                                     "Any part of a file or folder name works.")
            self.stack.setCurrentWidget(self.empty)

    # ---- keyboard
    def eventFilter(self, obj, e):
        if obj is self.edit and e.type() == QEvent.Type.KeyPress:
            k = e.key()
            mods = e.modifiers()
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            K = Qt.Key
            if k == K.Key_Down or (ctrl and k == K.Key_N):
                self.move_selection(1)
                return True
            if k == K.Key_Up or (ctrl and k == K.Key_P):
                self.move_selection(-1)
                return True
            if k == K.Key_PageDown:
                self.move_selection(7)
                return True
            if k == K.Key_PageUp:
                self.move_selection(-7)
                return True
            if k in (K.Key_Return, K.Key_Enter):
                self.reveal_current() if ctrl else self.open_current()
                return True
            if k == K.Key_Tab:
                self.cycle_filter(1)
                return True
            if k == K.Key_Backtab:
                self.cycle_filter(-1)
                return True
            if k == K.Key_Escape:
                if self.edit.text():
                    self.edit.clear()
                else:
                    self.hide()
                return True
            if ctrl and k == K.Key_C and not self.edit.hasSelectedText():
                self.copy_path()
                return True
        return super().eventFilter(obj, e)

    def move_selection(self, step: int) -> None:
        n = self.model.rowCount()
        if not n:
            return
        cur = self.list.currentIndex().row()
        new = max(0, min(n - 1, (0 if cur < 0 else cur) + step))
        idx = self.model.index(new)
        self.list.setCurrentIndex(idx)
        self.list.scrollTo(idx)

    # ---- actions
    def current(self) -> Result | None:
        idx = self.list.currentIndex()
        return idx.data(Qt.ItemDataRole.UserRole) if idx.isValid() else None

    def _gone(self, r: Result) -> bool:
        if os.path.exists(r.path):
            return False
        self.index.apply([("deleted", r.path, None)])
        self.footer.flash("That item no longer exists — removed from results")
        self.run_search()
        return True

    def open_current(self) -> None:
        r = self.current()
        if r is None or self._gone(r):
            return
        self.hide()
        try:
            os.startfile(r.path)
        except OSError:
            subprocess.Popen(f'explorer.exe /select,"{r.path}"')

    def reveal_current(self) -> None:
        r = self.current()
        if r is None or self._gone(r):
            return
        self.hide()
        subprocess.Popen(f'explorer.exe /select,"{r.path}"')

    def copy_path(self) -> None:
        r = self.current()
        if r is not None:
            QGuiApplication.clipboard().setText(r.path)
            self.footer.flash("Path copied to clipboard")

    def copy_name(self) -> None:
        r = self.current()
        if r is not None:
            QGuiApplication.clipboard().setText(r.name)
            self.footer.flash("Name copied to clipboard")

    def _context_menu(self, pos) -> None:
        idx = self.list.indexAt(pos)
        if not idx.isValid():
            return
        self.list.setCurrentIndex(idx)
        m = styled_menu(self.t, self)
        a_open = m.addAction("Open")
        a_reveal = m.addAction("Show in folder")
        m.addSeparator()
        a_copy = m.addAction("Copy path")
        a_name = m.addAction("Copy name")
        self._menu_open = True
        try:
            act = m.exec(self.list.viewport().mapToGlobal(pos))
        finally:
            self._menu_open = False
        if act is a_open:
            self.open_current()
        elif act is a_reveal:
            self.reveal_current()
        elif act is a_copy:
            self.copy_path()
        elif act is a_name:
            self.copy_name()
        self.edit.setFocus()


def styled_menu(t: Theme, parent=None) -> QMenu:
    m = QMenu(parent)
    m.setWindowFlags(m.windowFlags() | Qt.WindowType.FramelessWindowHint
                     | Qt.WindowType.NoDropShadowWindowHint)
    m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    m.setFont(ui_font(13))
    m.setStyleSheet(
        f"QMenu{{background:{css(t.surface)};border:1px solid {css(t.border)};border-radius:10px;"
        f"padding:5px;color:{css(t.text)};}}"
        f"QMenu::item{{padding:7px 26px 7px 14px;border-radius:6px;background:transparent;}}"
        f"QMenu::item:selected{{background:{css(t.selected)};}}"
        f"QMenu::item:disabled{{color:{css(t.faint)};}}"
        f"QMenu::separator{{height:1px;background:{css(t.divider)};margin:5px 8px;}}"
        f"QMenu::indicator{{width:0;}}")
    return m
