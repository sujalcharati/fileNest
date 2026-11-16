"""Command-line helpers:  python -m filenest.cli scan | find <query> [--kind images]"""
from __future__ import annotations

import argparse
import sys
import time

from .config import DB_PATH, load_settings
from .indexer import Excluder, Index, fixed_drives


def roots_from(settings: dict) -> list[str]:
    roots = list(settings.get("drives") or fixed_drives())
    for folder in settings.get("extra_folders") or []:
        if not any(folder.lower().startswith(r.lower()) for r in roots):
            roots.append(folder)
    return roots


def make_index(settings: dict) -> Index:
    ex = Excluder(settings["exclude_folder_names"], settings["exclude_paths"])
    return Index(DB_PATH, ex)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="filenest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="build the index now")
    f = sub.add_parser("find", help="search the index")
    f.add_argument("query", nargs="*")
    f.add_argument("--kind", default="all")
    f.add_argument("-n", type=int, default=15)
    args = ap.parse_args(argv)

    settings = load_settings()
    index = make_index(settings)

    if args.cmd == "scan":
        roots = roots_from(settings)
        print("Scanning:", ", ".join(roots), flush=True)
        t0 = time.perf_counter()
        n = index.rebuild(roots, progress=lambda c, d: print(f"\r{c:>10,} items  {d[:90]:<90}",
                                                               end="", flush=True))
        print(f"\nDone: {n:,} items in {time.perf_counter() - t0:.1f}s -> {DB_PATH}")
        return 0

    if not index.ready:
        print("No index yet - run:  python -m filenest.cli scan")
        return 1
    q = " ".join(args.query)
    t0 = time.perf_counter()
    rows, total, capped = index.search(q, args.kind, limit=args.n)
    ms = (time.perf_counter() - t0) * 1000
    print(f"{total:,}{'+' if capped else ''} matches in {ms:.1f} ms")
    for r in rows:
        print(("[D] " if r.is_dir else "    ") + r.path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
