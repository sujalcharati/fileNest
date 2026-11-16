"""FileNest application: tray icon, hotkey, background indexing and live updates."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import winfx
from .cli import make_index, roots_from
from .config import DATA_DIR, LOG_PATH, SETTINGS_PATH, load_settings
from .icon import make_app_icon
from .theme import build_theme
from .ui import HOTKEY_ID, SearchWindow, styled_menu
from .watcher import Watcher

log = logging.getLogger("filenest")
SERVER_NAME = "FileNest.single-instance.v1"


class Controller(QObject):
    progress = Signal(int, str)
    finished = Signal(object)
    changed = Signal(int)

    def __init__(self, app: QApplication, args: argparse.Namespace, server: QLocalServer | None):
        super().__init__()
        self.app = app
        self.args = args
        self.settings = load_settings()
        self.roots = roots_from(self.settings)
        self.index = make_index(self.settings)
        self.theme = build_theme()
        self.icon = make_app_icon()
        app.setWindowIcon(self.icon)

        self.window = SearchWindow(self.theme, self.index, acrylic=bool(self.settings.get("acrylic", True)))
        self.window.setWindowIcon(self.icon)
        self.window.hotkeyPressed.connect(self.window.toggle)

        self._stop = threading.Event()
        self._rebuild_thread: threading.Thread | None = None
        self.progress.connect(self.window.set_build_progress)
        self.finished.connect(self._on_rebuilt)
        self.changed.connect(lambda _n: None)

        self.hotkey = self._register_hotkey()
        self._make_tray()

        if server is not None:
            self.server = server
            server.newConnection.connect(self._on_instance_message)

        self.watcher = Watcher(self.index, self.index.excluder, on_change=self.changed.emit)
        self.watcher.start(self.roots)

        if self._is_stale():
            self.rebuild()
        self._stale_timer = QTimer(self, interval=30 * 60 * 1000, timeout=self._check_stale)
        self._stale_timer.start()
        app.aboutToQuit.connect(self.shutdown)

        if not args.background:
            QTimer.singleShot(150, self.window.summon)
            if not self.index.ready:
                self.tray.showMessage("FileNest is setting up",
                                      "Building your file index. This takes about a minute, once.",
                                      self.icon, 4000)

    # ---- hotkey / tray
    def _register_hotkey(self) -> str | None:
        hwnd = int(self.window.winId())
        for spec in self.settings.get("hotkeys") or []:
            if winfx.register_hotkey(hwnd, HOTKEY_ID, spec):
                log.info("hotkey registered: %s", spec)
                return spec
            log.warning("hotkey %s is taken by another app", spec)
        return None

    def _make_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.icon, self)
        hk = self.hotkey or "no shortcut"
        self.tray.setToolTip(f"FileNest — press {hk} to search")
        menu = styled_menu(self.theme)
        a_open = menu.addAction(f"Search files      {self.hotkey or ''}".rstrip())
        a_open.triggered.connect(self.window.summon)
        menu.addSeparator()
        self.a_rebuild = menu.addAction("Rebuild index now")
        self.a_rebuild.triggered.connect(lambda: self.rebuild(force=True))
        self.a_startup = menu.addAction("Start with Windows")
        self.a_startup.setCheckable(True)
        self.a_startup.setChecked(winfx.is_startup_enabled())
        self.a_startup.toggled.connect(self._toggle_startup)
        a_settings = menu.addAction("Open settings file")
        a_settings.triggered.connect(lambda: os.startfile(str(SETTINGS_PATH)))
        menu.addSeparator()
        a_quit = menu.addAction("Quit FileNest")
        a_quit.triggered.connect(self.app.quit)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.window.summon()

    def _toggle_startup(self, on: bool) -> None:
        try:
            winfx.set_startup(on)
        except OSError:
            log.exception("could not change startup setting")
            self.a_startup.setChecked(winfx.is_startup_enabled())

    def _on_instance_message(self) -> None:
        sock = self.server.nextPendingConnection()
        if sock is not None:
            sock.waitForReadyRead(200)
            sock.readAll()
            sock.disconnectFromServer()
        self.window.summon()

    # ---- indexing
    def _is_stale(self) -> bool:
        if not self.index.ready:
            return True
        ts = self.index.scanned_at() or 0
        return time.time() - ts > float(self.settings.get("rescan_every_hours", 6)) * 3600

    def _check_stale(self) -> None:
        if self._is_stale():
            self.rebuild()

    def rebuild(self, force: bool = False) -> None:
        if self._rebuild_thread is not None and self._rebuild_thread.is_alive():
            return
        self.a_rebuild.setEnabled(False)
        self.progress.emit(0, "")

        def work():
            n = None
            try:
                n = self.index.rebuild(self.roots, progress=self.progress.emit, stop=self._stop)
            except Exception:
                log.exception("index rebuild failed")
            self.finished.emit(n)

        self._rebuild_thread = threading.Thread(target=work, name="filenest-index", daemon=True)
        self._rebuild_thread.start()

    def _on_rebuilt(self, n) -> None:
        self.a_rebuild.setEnabled(True)
        self.window.build_finished()
        if n is not None and not self.window.isVisible() and not self.args.background:
            self.tray.showMessage("FileNest is ready",
                                  f"{n:,} files indexed. Press {self.hotkey or 'the tray icon'} to search.",
                                  self.icon, 3000)

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self.watcher.stop()
        except Exception:
            pass
        winfx.unregister_hotkey(int(self.window.winId()), HOTKEY_ID)
        self.tray.hide()
        self.index.close()


# --------------------------------------------------------------------------- entry point

def _setup_logging() -> None:
    logging.basicConfig(
        filename=str(LOG_PATH), level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="FileNest")
    ap.add_argument("--background", action="store_true", help="start hidden in the tray")
    # testing helpers
    ap.add_argument("--query", default=None)
    ap.add_argument("--filter", default=None)
    ap.add_argument("--screenshot", default=None)
    ap.add_argument("--delay", type=int, default=1200)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    args = _parse(sys.argv[1:] if argv is None else argv)
    winfx.set_app_id("FileNest.App")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("FileNest")
    app.setQuitOnLastWindowClosed(False)

    server = None
    if not args.screenshot:
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(300):  # already running: ask it to show itself
            winfx.allow_any_foreground()
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(300)
            return 0
        QLocalServer.removeServer(SERVER_NAME)
        server = QLocalServer()
        server.listen(SERVER_NAME)

    ctrl = Controller(app, args, server)

    if args.screenshot:
        w = ctrl.window
        w.pinned = True

        def prepare():
            if args.filter:
                for i, b in enumerate(w.chips):
                    if b.property("filter_key") == args.filter:
                        b.setChecked(True)
                        w._chip_clicked(i)
            if args.query is not None:
                w.edit.setText(args.query)
                w.edit.deselect()
                w.run_search()

        def shoot():
            g = w.frameGeometry()
            pad = 40
            pm = QGuiApplication.primaryScreen().grabWindow(
                0, g.x() - pad, g.y() - pad, g.width() + 2 * pad, g.height() + 2 * pad)
            pm.save(args.screenshot)
            app.quit()

        QTimer.singleShot(500, prepare)
        QTimer.singleShot(args.delay, shoot)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
