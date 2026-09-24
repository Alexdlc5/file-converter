"""Picks the right converter for a file and runs it.

Every converter writes into a private temporary folder; finished files are
moved next to the original (or into the chosen folder) only on success, so a
failed or cancelled conversion never leaves half-written files behind.
"""

import logging
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import formats
from .tools import Cancelled, ConversionError

log = logging.getLogger("converter")

QUALITIES = ("best", "balanced", "small")


@dataclass
class Job:
    src: Path
    target: str
    out_dir: Path
    quality: str = "balanced"
    progress: Callable[[float], None] = lambda fraction: None
    cancel: threading.Event = field(default_factory=threading.Event)
    # Filled in by convert():
    src_ext: str = ""
    stem: str = ""
    work_dir: Path = None

    def out(self, ext: str = None, suffix: str = "") -> Path:
        """Path for an output file inside the work folder."""
        return self.work_dir / f"{self.stem}{suffix}.{ext or self.target}"

    def pick(self, best, balanced, small):
        return {"best": best, "balanced": balanced, "small": small}[self.quality]

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()


class Converter:
    """Base class. Subclasses list what they read and write."""

    name = "converter"

    def available(self) -> bool:
        return True

    def targets(self, ext: str, path: Path) -> set:
        raise NotImplementedError

    def convert(self, job: Job) -> list:
        raise NotImplementedError


def _registry():
    from .archives import ArchiveConverter
    from .data import DataConverter, StructuredConverter
    from .documents import LibreOfficeConverter, PandocConverter
    from .fonts import FontConverter
    from .images import ImageConverter
    from .media import MediaConverter, SubtitleConverter
    from .pdfs import PdfConverter

    # Earlier entries win when two converters can make the same format.
    # LibreOffice goes first because it keeps Office layouts intact.
    return [
        LibreOfficeConverter(), ImageConverter(), MediaConverter(), SubtitleConverter(),
        PdfConverter(), PandocConverter(), DataConverter(), StructuredConverter(),
        ArchiveConverter(), FontConverter(),
    ]


_converters = None
_lock = threading.Lock()


def converters():
    global _converters
    with _lock:
        if _converters is None:
            _converters = [c for c in _registry() if _safe_available(c)]
        return _converters


def _safe_available(conv) -> bool:
    try:
        return conv.available()
    except Exception:
        log.exception("availability check failed for %s", conv.name)
        return False


def _targets(conv, ext, path) -> set:
    try:
        return conv.targets(ext, path)
    except Exception:
        log.exception("targets() failed in %s for %s", conv.name, path)
        return set()


def targets_for(path) -> list:
    """Formats this file can be converted to, grouped and ordered for menus."""
    path = Path(path)
    ext = formats.get_ext(path)
    found = set()
    for conv in converters():
        found |= _targets(conv, ext, path)
    found.discard(ext)
    return formats.sort_formats(found)


def hint_for(path) -> str:
    """Why a file has no conversions, and what would fix it."""
    ext = formats.get_ext(path)
    if not ext:
        return "This file has no extension, so its type is unknown."
    if ext in {"pptx", "ppt", "odp", "doc", "wpd"}:
        return f"Install LibreOffice (free) to convert .{ext} files, then restart the app."
    if formats.category(ext) in ("Video", "Audio"):
        return "ffmpeg is missing. Re-run the installer."
    return f"Converting .{ext} files isn't supported."


# Folders some conversions create next to the main file.
EXTRA_FOLDERS = {"_files": {"md", "rst", "org", "tex"}, "_pages": {"png", "jpg", "tiff", "webp"},
                 "_sheets": {"csv", "tsv"}}


def _unique_stem(out_dir: Path, base: str, target: str) -> str:
    """A name whose outputs won't overwrite anything already in out_dir."""
    extras = [suffix for suffix, targets in EXTRA_FOLDERS.items() if target in targets]
    n = 0
    while True:
        cand = base if n == 0 else f"{base} ({n})"
        names = [f"{cand}.{target}"] + [cand + suffix for suffix in extras]
        if not any((out_dir / name).exists() for name in names):
            return cand
        n += 1


def _move_unique(item: Path, out_dir: Path) -> Path:
    dest = out_dir / item.name
    if dest.exists():
        ext = formats.raw_ext(item) if item.is_file() else ""
        base = formats.stem(item) if ext else item.name
        n = 1
        while dest.exists():
            dest = out_dir / (f"{base} ({n}).{ext}" if ext else f"{base} ({n})")
            n += 1
    shutil.move(str(item), str(dest))
    return dest


def convert(src, target, out_dir=None, quality="balanced", progress=None, cancel=None) -> list:
    """Convert one file. Returns the paths created. Raises ConversionError or Cancelled."""
    src = Path(src).resolve()
    if not src.is_file():
        raise ConversionError("File not found.")
    out_dir = Path(out_dir).resolve() if out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = formats.get_ext(src)

    conv = next((c for c in converters() if target in _targets(c, ext, src)), None)
    if conv is None:
        raise ConversionError(f"Can't convert .{ext or '?'} to .{target}.")

    job = Job(src=src, target=target, out_dir=out_dir, quality=quality,
              progress=progress or (lambda f: None), cancel=cancel or threading.Event())
    job.src_ext = ext
    job.stem = _unique_stem(out_dir, formats.stem(src), target)

    with tempfile.TemporaryDirectory(prefix="fileconv-") as tmp:
        job.work_dir = Path(tmp) / "out"
        job.work_dir.mkdir()
        log.info("convert %s -> %s with %s", src, target, conv.name)
        try:
            outputs = conv.convert(job)
        except (ConversionError, Cancelled):
            raise
        except MemoryError:
            raise ConversionError("Ran out of memory. Try a smaller file.")
        except Exception as exc:
            log.exception("converter crashed")
            raise ConversionError(f"{type(exc).__name__}: {exc}") from exc
        job.check_cancel()
        outputs = [Path(p) for p in outputs if Path(p).exists()]
        if not outputs:
            raise ConversionError("The converter finished but produced no file.")
        return [_move_unique(p, out_dir) for p in outputs]
