"""Finding the external programs the converters use, and running them."""

import functools
import importlib.util
import locale
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("converter")

# Keep console windows from flashing up on Windows when the app runs without one.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class ConversionError(Exception):
    """A conversion failed; the message is shown to the user."""


class Cancelled(Exception):
    """The user pressed Cancel."""


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@functools.lru_cache(maxsize=None)
def ffmpeg_path():
    """The ffmpeg bundled with imageio-ffmpeg, else one on PATH."""
    if has_module("imageio_ffmpeg"):
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:  # binary missing for this platform
            log.warning("imageio-ffmpeg has no binary: %s", exc)
    return shutil.which("ffmpeg")


@functools.lru_cache(maxsize=None)
def ffmpeg_encoders() -> frozenset:
    exe = ffmpeg_path()
    if not exe:
        return frozenset()
    try:
        out = subprocess.run(
            [exe, "-hide_banner", "-encoders"], capture_output=True, text=True,
            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        # Encoder lines look like " V....D libx264   H.264 ..."
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
            names.add(parts[1])
    return frozenset(names)


@functools.lru_cache(maxsize=None)
def pandoc_path():
    """The pandoc bundled with pypandoc_binary, else one on PATH."""
    if has_module("pypandoc"):
        try:
            import pypandoc
            return pypandoc.get_pandoc_path()
        except Exception:
            pass
    return shutil.which("pandoc")


@functools.lru_cache(maxsize=None)
def soffice_path():
    """LibreOffice, if installed. Optional: it gives the best Office-file fidelity."""
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    candidates = []
    if os.name == "nt":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(var)
            if base:
                candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
        candidates.append(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice")
    else:
        candidates += [Path("/usr/bin/soffice"), Path("/opt/libreoffice/program/soffice"),
                       Path("/snap/bin/libreoffice")]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def run(cmd, cancel=None, timeout=None, cwd=None):
    """Run a program, returning its stdout. Raises ConversionError on failure."""
    log.info("run: %s", " ".join(str(c) for c in cmd))
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, cwd=cwd, creationflags=NO_WINDOW,
        )
    except OSError as exc:
        raise ConversionError(f"Could not start {Path(str(cmd[0])).name}: {exc}") from exc
    waited = 0.0
    while True:
        try:
            out, err = proc.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            waited += 0.25
            if (cancel is not None and cancel.is_set()) or (timeout and waited > timeout):
                proc.kill()
                proc.communicate()
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                raise ConversionError(f"{Path(str(cmd[0])).name} took too long and was stopped.")
    out_text = out.decode("utf-8", "replace")
    err_text = err.decode("utf-8", "replace")
    if proc.returncode != 0:
        log.warning("failed (%s): %s", proc.returncode, err_text[-2000:])
        raise ConversionError(last_lines(err_text) or f"{Path(str(cmd[0])).name} failed.")
    return out_text


def last_lines(text: str, n: int = 3) -> str:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return " ".join(lines[-n:])


def default_paper() -> str:
    """US Letter for North America, A4 everywhere else."""
    names = []
    for getter in (lambda: locale.getlocale()[0], lambda: os.environ.get("LANG")):
        try:
            names.append(getter() or "")
        except Exception:
            pass
    joined = " ".join(names).lower()
    if any(key in joined for key in ("_us", "_ca", "united states", "canada", "_ph", "_mx")):
        return "letter"
    return "a4"
