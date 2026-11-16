"""File categories: badge colours and the filter chips."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    color: str
    exts: frozenset


def _c(key: str, label: str, color: str, exts: str) -> Category:
    return Category(key, label, color, frozenset(exts.split()))


PDF = _c("pdf", "PDF", "#E5484D", "pdf")
WORD = _c("word", "Document", "#3E7BFA", "doc docx docm odt rtf pages wps")
SHEET = _c("sheet", "Spreadsheet", "#2EAA6A", "xls xlsx xlsm xlsb csv tsv ods numbers")
SLIDES = _c("slides", "Presentation", "#F2762E", "ppt pptx pptm odp key")
TEXT = _c("text", "Text", "#8B8D98", "txt md markdown rst tex epub mobi log ini cfg conf")
IMAGE = _c("image", "Image", "#D6409F",
           "png jpg jpeg gif bmp webp svg heic heif ico tif tiff raw cr2 nef arw dng psd ai avif jfif")
VIDEO = _c("video", "Video", "#8E4EC6", "mp4 mkv avi mov wmv webm flv m4v mpg mpeg 3gp ts")
AUDIO = _c("audio", "Audio", "#12A594", "mp3 wav flac aac ogg m4a wma opus aiff mid midi amr")
CODE = _c("code", "Code", "#E09B2D",
          "py pyw ipynb js mjs cjs ts tsx jsx html htm css scss sass less json jsonc yml yaml toml "
          "xml java kt kts c h cpp cc hpp cs go rs php rb swift dart lua r sql sh bash zsh ps1 psm1 "
          "bat cmd vue svelte gradle ino asm")
ARCHIVE = _c("archive", "Archive", "#B0805A", "zip rar 7z tar gz tgz bz2 xz iso cab zst img")
APP = _c("app", "Application", "#5E7CE2", "exe msi lnk appx msix appxbundle msixbundle apk url")
FONT = _c("font", "Font", "#7A8B99", "ttf otf woff woff2 fon")

OTHER = Category("other", "File", "#7C7F8A", frozenset())
FOLDER = Category("folder", "Folder", "#F5B53D", frozenset())

_ALL = (PDF, WORD, SHEET, SLIDES, TEXT, IMAGE, VIDEO, AUDIO, CODE, ARCHIVE, APP, FONT)
_BY_EXT = {e: c for c in _ALL for e in c.exts}


def category_for(ext: str, is_dir: bool) -> Category:
    if is_dir:
        return FOLDER
    return _BY_EXT.get(ext, OTHER)


_DOC_EXTS = (PDF.exts | WORD.exts | SHEET.exts | SLIDES.exts | TEXT.exts) - {"log", "ini", "cfg", "conf"}

# (key, chip label, extensions or None)
FILTERS: list[tuple[str, str, frozenset | None]] = [
    ("all", "All", None),
    ("files", "Files", None),
    ("folders", "Folders", None),
    ("docs", "Documents", frozenset(_DOC_EXTS)),
    ("images", "Images", IMAGE.exts),
    ("media", "Media", VIDEO.exts | AUDIO.exts),
    ("code", "Code", CODE.exts),
    ("archives", "Archives", ARCHIVE.exts),
    ("apps", "Apps", APP.exts),
]
FILTER_EXTS = {k: e for k, _, e in FILTERS}
