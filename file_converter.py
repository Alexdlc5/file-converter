#!/usr/bin/env python3
"""File Converter.

Open the app (the desktop shortcut does this):
    python file_converter.py [files...]

Or use it from a terminal:
    python file_converter.py --to pdf report.docx notes.md
    python file_converter.py --to mp3 --quality best --out ~/Music video.mov
    python file_converter.py --formats photo.heic     # what can this file become?
    python file_converter.py --check                  # which converters are ready?
"""

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# pythonw.exe (used by the Windows shortcut) has no console; give output somewhere to go.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


def setup_logging():
    from converter.gui import config_dir

    handlers = [logging.StreamHandler(sys.stderr)]
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(config_dir() / "file-converter.log", maxBytes=1_000_000,
                                            backupCount=1, encoding="utf-8"))
    except OSError:
        pass
    handlers[0].setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=handlers)


def check():
    from converter import converters, formats
    from converter.tools import ffmpeg_path, pandoc_path, soffice_path

    print("File Converter status\n")
    for name, path, what in (
        ("ffmpeg", ffmpeg_path(), "video, audio, subtitles"),
        ("pandoc", pandoc_path(), "Word, Markdown, HTML, EPUB and other documents"),
        ("LibreOffice", soffice_path(), "optional: PowerPoint, old .doc/.xls/.ppt, best Office -> PDF"),
    ):
        print(f"  {'OK ' if path else '-- '} {name:<12} {what}")
        if path:
            print(f"       {path}")
    print("\nConverters loaded:", ", ".join(c.name for c in converters()))
    readable = {ext for ext in formats.FORMATS
                if any(c.targets(ext, Path(f"x.{ext}")) for c in converters())}
    print(f"File types it can open: {len(readable)}")
    return 0


def cli(args):
    from converter import Cancelled, ConversionError, convert, formats, targets_for

    target = formats.ALIASES.get(args.to.lower().lstrip("."), args.to.lower().lstrip("."))
    failures = 0
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            print(f"✗ {name}: not found")
            failures += 1
            continue
        options = targets_for(path)
        if target not in options:
            print(f"✗ {name}: can't convert to .{target}. Options: {', '.join(options) or 'none'}")
            failures += 1
            continue
        try:
            outputs = convert(path, target, args.out, args.quality)
            for out in outputs:
                print(f"✓ {name} -> {out}")
        except (ConversionError, Cancelled) as exc:
            print(f"✗ {name}: {exc}")
            failures += 1
        except KeyboardInterrupt:
            print("Stopped.")
            return 130
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description="Convert files between formats.")
    parser.add_argument("files", nargs="*", help="files (or folders) to convert")
    parser.add_argument("--to", help="convert to this format without opening the window (e.g. pdf, mp3)")
    parser.add_argument("--out", help="folder for the results (default: next to each file)")
    parser.add_argument("--quality", choices=["best", "balanced", "small"], default="balanced")
    parser.add_argument("--formats", action="store_true", help="list what each file can be converted to")
    parser.add_argument("--check", action="store_true", help="show which converters are installed")
    args = parser.parse_args()
    setup_logging()

    if args.check:
        return check()
    if args.formats:
        from converter import formats, hint_for, targets_for
        for name in args.files:
            options = targets_for(name)
            print(f"{name}:")
            if options:
                for fmt in options:
                    print(f"    {fmt:<8} {formats.label(fmt)}")
            else:
                print("    " + hint_for(name))
        return 0
    if args.to:
        return cli(args)

    try:
        from converter.gui import run_app
        run_app(args.files)
    except Exception as exc:
        logging.getLogger("converter").exception("app crashed")
        try:
            from tkinter import messagebox
            messagebox.showerror("File Converter", f"Something went wrong:\n{exc}")
        except Exception:
            print(f"File Converter failed to start: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
