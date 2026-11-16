"""Scanning drives and the SQLite search index.

The index is a plain table of every file/folder (name, full path, size, date)
plus an FTS5 *trigram* index on the name, which makes substring search
("xyz" matches "old_xyz_final.pdf") fast even with millions of entries.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sqlite3
import stat as stat_mod
import string
import threading
import time
from collections import namedtuple
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .filetypes import FILTER_EXTS

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4

Result = namedtuple("Result", "name path is_dir ext size mtime")

BASE_SCHEMA = """
CREATE TABLE files(
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL,
    path   TEXT NOT NULL,
    is_dir INTEGER NOT NULL,
    ext    TEXT NOT NULL DEFAULT '',
    size   INTEGER,
    mtime  REAL
);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""

POST_SCHEMA = """
CREATE INDEX idx_path  ON files(path COLLATE NOCASE);
CREATE INDEX idx_mtime ON files(mtime);
CREATE VIRTUAL TABLE files_fts USING fts5(
    name, content='files', content_rowid='id', tokenize='trigram'
);
INSERT INTO files_fts(files_fts) VALUES('rebuild');
CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, name) VALUES (new.id, new.name);
END;
CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name) VALUES ('delete', old.id, old.name);
END;
"""

INSERT_SQL = "INSERT INTO files(name, path, is_dir, ext, size, mtime) VALUES (?, ?, ?, ?, ?, ?)"
COLS = "f.name, f.path, f.is_dir, f.ext, f.size, f.mtime"

# Noise we don't want in the "recently modified" list.
_RECENT_JUNK_EXT = {
    "log", "tmp", "temp", "etl", "db", "db-wal", "db-shm", "db-journal", "sqlite", "sqlite3",
    "dat", "lock", "ldb", "pf", "bak", "cache", "crdownload", "part", "json", "ini", "lnk",
    "pyc", "regtrans-ms", "blf", "jfm", "idx", "pma", "wal", "shm", "evtx", "",
}

# Paths that are usually tool/system clutter rather than "your" files: ranked lower.
_NOISE_MARKERS = (
    "\\appdata\\", "\\.", "\\anaconda3\\", "\\miniconda3\\", "\\mingw", "\\msys",
    "\\drivers\\", "\\$", "\\pkgs\\", "\\dist-packages\\", "\\vendor\\", "\\build\\",
)


# --------------------------------------------------------------------------- helpers

def fixed_drives() -> list[str]:
    """All internal (fixed) drives, e.g. ['C:\\', 'D:\\']."""
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            root = f"{letter}:\\"
            if k32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                out.append(root)
    return out


def ext_of(name: str) -> str:
    i = name.rfind(".")
    return name[i + 1:].lower() if i > 0 else ""


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _remove_db_files(p: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(str(p) + suffix)
        except FileNotFoundError:
            pass


class Excluder:
    """Decides which folders are skipped (Windows, caches, node_modules, ...)."""

    def __init__(self, names: Iterable[str], paths: Iterable[str]):
        self.names = {n.lower() for n in names}
        norm = []
        for p in paths:
            p = os.path.expandvars(p)
            if "%" in p:  # unknown variable, ignore
                continue
            norm.append(os.path.normcase(os.path.abspath(p)).rstrip("\\"))
        self.paths = set(norm)
        self.prefixes = tuple(p + "\\" for p in norm)

    def dir_excluded(self, path: str, name: str) -> bool:
        """Fast check used while scanning (parents are already known to be fine)."""
        return name.lower() in self.names or os.path.normcase(path) in self.paths

    def path_excluded(self, path: str) -> bool:
        """Full check used for live change events."""
        lp = os.path.normcase(path).rstrip("\\")
        if lp in self.paths or lp.startswith(self.prefixes):
            return True
        return any(part in self.names for part in lp.split("\\"))


def scan_tree(root: str, excluder: Excluder, stop: threading.Event | None = None,
              on_dir: Callable[[str], None] | None = None) -> Iterator[tuple]:
    """Yield a row for every file and folder below `root` (not following links)."""
    stack = [root]
    while stack:
        if stop is not None and stop.is_set():
            return
        d = stack.pop()
        if on_dir is not None:
            on_dir(d)
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_symlink() or e.is_junction():
                        continue
                    is_dir = e.is_dir(follow_symlinks=False)
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                attrs = getattr(st, "st_file_attributes", 0)
                if attrs & FILE_ATTRIBUTE_HIDDEN and attrs & FILE_ATTRIBUTE_SYSTEM:
                    continue  # desktop.ini, thumbs.db and other OS plumbing
                name = e.name
                if is_dir:
                    if excluder.dir_excluded(e.path, name):
                        continue
                    stack.append(e.path)
                    yield (name, e.path, 1, "", None, st.st_mtime)
                else:
                    yield (name, e.path, 0, ext_of(name), st.st_size, st.st_mtime)


# --------------------------------------------------------------------------- index

class Index:
    def __init__(self, db_path: Path, excluder: Excluder):
        self.db_path = Path(db_path)
        self.excluder = excluder
        self.lock = threading.RLock()
        self.conn: sqlite3.Connection | None = None
        self._building = False
        self._buffer: list = []
        self._open()

    # -- lifecycle
    def _open(self) -> None:
        self.conn = None
        if not self.db_path.exists():
            return
        try:
            c = sqlite3.connect(str(self.db_path), check_same_thread=False)
            row = c.execute("SELECT value FROM meta WHERE key='version'").fetchone()
            if not row or row[0] != SCHEMA_VERSION:
                c.close()
                return
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA temp_store=MEMORY")
            c.execute("PRAGMA cache_size=-32000")
            self.conn = c
        except sqlite3.DatabaseError:
            log.exception("index database is unreadable; it will be rebuilt")
            self.conn = None

    def close(self) -> None:
        with self.lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

    @property
    def ready(self) -> bool:
        return self.conn is not None

    @property
    def building(self) -> bool:
        return self._building

    def scanned_at(self) -> float | None:
        with self.lock:
            if self.conn is None:
                return None
            row = self.conn.execute("SELECT value FROM meta WHERE key='scanned_at'").fetchone()
        return float(row[0]) if row else None

    def count(self) -> int:
        with self.lock:
            if self.conn is None:
                return 0
            return self.conn.execute("SELECT count(*) FROM files").fetchone()[0]

    # -- searching
    @staticmethod
    def _kind_clause(kind: str) -> tuple[str, list]:
        if kind == "files":
            return " AND f.is_dir = 0", []
        if kind == "folders":
            return " AND f.is_dir = 1", []
        exts = FILTER_EXTS.get(kind)
        if exts:
            exts = sorted(exts)
            return f" AND f.is_dir = 0 AND f.ext IN ({','.join('?' * len(exts))})", exts
        return "", []

    def search(self, query: str, kind: str = "all", limit: int = 200,
               candidates: int = 4000) -> tuple[list[Result], int, bool]:
        """Return (results, number of matches found, whether that number is capped)."""
        terms = query.split()
        if not terms:
            rows = self.recent(kind, limit=40)
            return rows, len(rows), False

        name_terms = [t for t in terms if "\\" not in t and "/" not in t]
        path_terms = [t.replace("/", "\\").strip("\\") for t in terms if "\\" in t or "/" in t]
        fts_terms = [t for t in name_terms if len(t) >= 3]
        short_terms = [t for t in name_terms if len(t) < 3]

        where: list[str] = []
        params: list = []
        if fts_terms:
            src = "files_fts JOIN files f ON f.id = files_fts.rowid"
            where.append("files_fts MATCH ?")
            params.append(" AND ".join('"' + t.replace('"', '""') + '"' for t in fts_terms))
        else:
            src = "files f"
        for t in short_terms:
            where.append("f.name LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(t)}%")
        for t in path_terms:
            if t:
                where.append("f.path LIKE ? ESCAPE '\\'")
                params.append(f"%{_escape_like(t)}%")
        if not where:
            where.append("1")
        kind_sql, kind_params = self._kind_clause(kind)
        sql = f"SELECT {COLS} FROM {src} WHERE {' AND '.join(where)}{kind_sql} LIMIT {candidates}"

        with self.lock:
            if self.conn is None:
                return [], 0, False
            try:
                rows = self.conn.execute(sql, params + kind_params).fetchall()
            except sqlite3.OperationalError:
                log.exception("search failed: %r", query)
                return [], 0, False

        self._rank(rows, " ".join(name_terms))
        return [Result(*r) for r in rows[:limit]], len(rows), len(rows) >= candidates

    @staticmethod
    def _rank(rows: list, query: str) -> None:
        q = query.lower().strip()
        first = q.split()[0] if q else ""

        def key(r):
            name = r[0].lower()
            stem = name.rsplit(".", 1)[0] if (not r[2] and "." in name) else name
            if q and (name == q or stem == q):
                s = 0
            elif q and name.startswith(q):
                s = 1
            elif first and name.startswith(first):
                s = 2
            else:
                i = name.find(first) if first else -1
                s = 3 if i > 0 and not name[i - 1].isalnum() else 4
            low = r[1].lower()
            noise = 1 if any(m in low for m in _NOISE_MARKERS) else 0
            return (s, noise, r[1].count("\\"), len(name), name)

        rows.sort(key=key)

    def recent(self, kind: str = "all", limit: int = 40) -> list[Result]:
        kind_sql, kind_params = self._kind_clause(kind)
        if kind != "folders":
            kind_sql += " AND f.is_dir = 0"
        sql = (f"SELECT {COLS} FROM files f WHERE f.mtime <= ?{kind_sql} "
               f"ORDER BY f.mtime DESC LIMIT 800")
        with self.lock:
            if self.conn is None:
                return []
            rows = self.conn.execute(sql, [time.time() + 86400] + kind_params).fetchall()
        out = []
        for r in rows:
            low = r[1].lower()
            if r[0].startswith(("~$", ".")) or any(m in low for m in _NOISE_MARKERS):
                continue
            if kind != "folders" and r[3] in _RECENT_JUNK_EXT:
                continue
            out.append(Result(*r))
            if len(out) >= limit:
                break
        return out

    # -- live updates (from the file watcher)
    def apply(self, events: list[tuple]) -> None:
        """events: ('created'|'modified'|'deleted', path, None) or ('moved', src, dest)."""
        with self.lock:
            if self._building:
                self._buffer.extend(events)  # replayed onto the fresh index after the swap
            if self.conn is None:
                return
            try:
                for kind, src, dest in events:
                    if kind == "deleted":
                        self._delete_tree(src)
                    elif kind == "moved":
                        self._delete_tree(src)
                        self._add(dest, deep=True)
                    elif kind == "created":
                        self._add(src, deep=True)
                    elif kind == "modified":
                        self._add(src, deep=False)
                self.conn.commit()
            except sqlite3.Error:
                log.exception("applying %d change(s) failed", len(events))
                self.conn.rollback()

    def _delete_tree(self, path: str) -> None:
        path = path.rstrip("\\")
        self.conn.execute("DELETE FROM files WHERE path = ? COLLATE NOCASE", (path,))
        self.conn.execute(
            "DELETE FROM files WHERE path >= ? COLLATE NOCASE AND path < ? COLLATE NOCASE",
            (path + "\\", path + "]"),  # ']' sorts right after '\'
        )

    def _add(self, path: str, deep: bool) -> None:
        path = path.rstrip("\\")
        if self.excluder.path_excluded(path):
            return
        try:
            st = os.stat(path, follow_symlinks=False)
        except OSError:
            self._delete_tree(path)
            return
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & FILE_ATTRIBUTE_HIDDEN and attrs & FILE_ATTRIBUTE_SYSTEM:
            return
        name = os.path.basename(path)
        if not name:
            return
        is_dir = stat_mod.S_ISDIR(st.st_mode)
        is_link = os.path.islink(path) or os.path.isjunction(path)
        if is_link:
            return
        self.conn.execute("DELETE FROM files WHERE path = ? COLLATE NOCASE", (path,))
        self.conn.execute(INSERT_SQL, (
            name, path, int(is_dir), "" if is_dir else ext_of(name),
            None if is_dir else st.st_size, st.st_mtime,
        ))
        if is_dir and deep:
            self.conn.execute(
                "DELETE FROM files WHERE path >= ? COLLATE NOCASE AND path < ? COLLATE NOCASE",
                (path + "\\", path + "]"),
            )
            self.conn.executemany(INSERT_SQL, scan_tree(path, self.excluder))

    # -- full (re)build
    def rebuild(self, roots: list[str], progress: Callable[[int, str], None] | None = None,
                stop: threading.Event | None = None) -> int | None:
        """Scan everything into a fresh database, then swap it in. Returns item count."""
        tmp = self.db_path.with_name(self.db_path.stem + ".building.db")
        _remove_db_files(tmp)
        with self.lock:
            self._building = True
            self._buffer = []
        ok = False
        try:
            c = sqlite3.connect(str(tmp))
            c.executescript(
                "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=MEMORY;"
                "PRAGMA cache_size=-64000;" + BASE_SCHEMA
            )
            n = 0
            last = 0.0
            batch: list = []
            current = [""]

            def on_dir(d: str) -> None:
                current[0] = d

            for root in roots:
                for row in scan_tree(root, self.excluder, stop, on_dir):
                    batch.append(row)
                    if len(batch) >= 5000:
                        c.executemany(INSERT_SQL, batch)
                        n += len(batch)
                        batch.clear()
                        now = time.monotonic()
                        if progress and now - last > 0.12:
                            progress(n, current[0])
                            last = now
                if stop is not None and stop.is_set():
                    c.close()
                    return None
            if batch:
                c.executemany(INSERT_SQL, batch)
                n += len(batch)
            if progress:
                progress(n, "Optimising the index…")
            c.executescript(POST_SCHEMA)
            c.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", [
                ("version", SCHEMA_VERSION),
                ("scanned_at", str(time.time())),
                ("roots", "|".join(roots)),
            ])
            c.commit()
            c.close()

            with self.lock:
                if self.conn is not None:
                    self.conn.close()
                    self.conn = None
                _remove_db_files(self.db_path)
                os.replace(tmp, self.db_path)
                self._open()
                buffered, self._buffer = self._buffer, []
                self._building = False
            if buffered:
                self.apply(buffered)
            ok = True
            log.info("index rebuilt: %d items", n)
            return n
        finally:
            with self.lock:
                self._building = False
                self._buffer = []
            if not ok:
                try:
                    _remove_db_files(tmp)
                except OSError:
                    pass
