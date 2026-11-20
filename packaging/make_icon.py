"""Render the FileNest icon (filenest/icon.py) into a multi-size Windows .ico file."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from filenest.icon import paint_icon  # noqa: E402

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def main(out: Path) -> None:
    app = QGuiApplication(sys.argv[:1])  # noqa: F841  (needed for QPixmap)
    pngs = []
    for s in SIZES:
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        paint_icon(s).save(buf, "PNG")
        buf.close()
        pngs.append(bytes(data))

    # ICO = header + one directory entry per image + PNG payloads.
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries = b""
    for s, png in zip(SIZES, pngs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(header + entries + b"".join(pngs))
    print(f"icon written: {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "FileNest.ico")
