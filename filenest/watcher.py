"""Keeps the index up to date as files are created, renamed, moved or deleted."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .indexer import Excluder, Index

log = logging.getLogger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, sink: Callable[[tuple], None], excluder: Excluder):
        self.sink = sink
        self.excluder = excluder

    def on_any_event(self, ev) -> None:
        kind = ev.event_type
        if kind not in ("created", "deleted", "moved", "modified"):
            return
        if kind == "modified" and ev.is_directory:
            return
        src = ev.src_path if isinstance(ev.src_path, str) else ev.src_path.decode()
        if kind == "moved":
            dest = ev.dest_path if isinstance(ev.dest_path, str) else ev.dest_path.decode()
            src_ex = self.excluder.path_excluded(src)
            dest_ex = self.excluder.path_excluded(dest)
            if src_ex and dest_ex:
                return
            if dest_ex:
                self.sink(("deleted", src, None))
            elif src_ex:
                self.sink(("created", dest, None))
            else:
                self.sink(("moved", src, dest))
            return
        if not self.excluder.path_excluded(src):
            self.sink((kind, src, None))


class Watcher:
    def __init__(self, index: Index, excluder: Excluder,
                 on_change: Callable[[int], None] | None = None):
        self.index = index
        self.excluder = excluder
        self.on_change = on_change
        self._queue: list[tuple] = []
        self._qlock = threading.Lock()
        self._stop = threading.Event()
        self._observer: Observer | None = None

    def _sink(self, ev: tuple) -> None:
        with self._qlock:
            self._queue.append(ev)

    def start(self, roots: list[str]) -> None:
        self._observer = Observer()
        handler = _Handler(self._sink, self.excluder)
        for root in roots:
            try:
                self._observer.schedule(handler, root, recursive=True)
            except Exception:
                log.exception("cannot watch %s", root)
        self._observer.daemon = True
        self._observer.start()
        threading.Thread(target=self._flush_loop, name="filenest-flush", daemon=True).start()

    def _flush_loop(self) -> None:
        while not self._stop.wait(1.5):
            with self._qlock:
                events, self._queue = self._queue, []
            if not events:
                continue
            seen_mod: set[str] = set()
            batch = []
            for ev in events:
                if ev[0] == "modified":
                    key = ev[1].lower()
                    if key in seen_mod:
                        continue
                    seen_mod.add(key)
                batch.append(ev)
            try:
                self.index.apply(batch)
            except Exception:
                log.exception("failed to apply file changes")
            if self.on_change is not None:
                self.on_change(len(batch))

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
