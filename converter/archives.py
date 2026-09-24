"""Archives: repack between ZIP and the TAR family (Python standard library only)."""

import os
import tarfile
import tempfile
import zipfile
from pathlib import Path

from .engine import Converter
from .tools import ConversionError

FORMATS = {"zip", "tar", "tar.gz", "tar.bz2", "tar.xz"}
TAR_MODE = {"tar": "", "tar.gz": "gz", "tar.bz2": "bz2", "tar.xz": "xz"}


def _extract(src, ext, dest: Path):
    dest = dest.resolve()
    try:
        if ext == "zip":
            with zipfile.ZipFile(src) as zf:
                for info in zf.infolist():
                    target = (dest / info.filename).resolve()
                    if dest not in target.parents and target != dest:
                        raise ConversionError("This archive contains unsafe paths; not extracting it.")
                zf.extractall(dest)
        else:
            with tarfile.open(src, "r:*") as tf:
                if hasattr(tarfile, "data_filter"):
                    tf.extractall(dest, filter="data")
                else:
                    for member in tf.getmembers():
                        target = (dest / member.name).resolve()
                        if dest not in target.parents or member.issym() or member.islnk():
                            raise ConversionError("This archive contains unsafe paths; not extracting it.")
                    tf.extractall(dest)
    except (zipfile.BadZipFile, tarfile.TarError, EOFError) as exc:
        raise ConversionError(f"This archive is damaged or not a .{ext} file ({exc}).") from exc
    except RuntimeError as exc:  # zipfile raises this for encrypted entries
        raise ConversionError(f"Couldn't open this archive ({exc}).") from exc


class ArchiveConverter(Converter):
    name = "archives"

    def targets(self, ext, path):
        return set(FORMATS) if ext in FORMATS else set()

    def convert(self, job):
        with tempfile.TemporaryDirectory(prefix="arc-") as tmp:
            root = Path(tmp)
            _extract(job.src, job.src_ext, root)
            job.check_cancel()
            out = job.out()
            entries = sorted(root.rglob("*"))
            if job.target == "zip":
                level = job.pick(9, 6, 9)
                with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
                    for path in entries:
                        job.check_cancel()
                        zf.write(path, path.relative_to(root).as_posix())
            else:
                with tarfile.open(out, "w:" + TAR_MODE[job.target]) as tf:
                    for child in sorted(os.listdir(root)):
                        job.check_cancel()
                        tf.add(root / child, arcname=child)
            return [out]
