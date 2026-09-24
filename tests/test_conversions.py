"""Makes a sample of every supported file type, then tries every conversion it offers.

    python tests/test_conversions.py            # prints a pass/fail table
    python -m pytest tests                      # same checks under pytest
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from converter import ConversionError, convert, targets_for  # noqa: E402
from converter.tools import ffmpeg_path, pandoc_path  # noqa: E402


def make_samples(folder: Path) -> list:
    from PIL import Image, ImageDraw

    folder.mkdir(parents=True, exist_ok=True)
    made = []

    def keep(path):
        made.append(Path(path))
        return Path(path)

    # Images
    img = Image.new("RGBA", (320, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((20, 20, 180, 180), fill=(30, 120, 220, 255))
    draw.rectangle((150, 60, 300, 160), fill=(240, 80, 40, 200))
    img.save(keep(folder / "picture.png"))
    img.convert("RGB").save(keep(folder / "photo.jpg"), quality=90)
    img.save(keep(folder / "picture.webp"))
    img.convert("RGB").save(keep(folder / "scan.bmp"))
    frames = [Image.new("RGB", (120, 90), (i * 40, 90, 200 - i * 30)) for i in range(5)]
    frames[0].save(keep(folder / "animation.gif"), save_all=True, append_images=frames[1:],
                   duration=120, loop=0)
    frames[0].save(keep(folder / "pages.tiff"), save_all=True, append_images=frames[1:3])
    img.save(keep(folder / "favicon.ico"))
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        img.convert("RGB").save(keep(folder / "iphone.heic"))
    except Exception:
        pass
    (keep(folder / "logo.svg")).write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
        '<rect width="120" height="80" rx="12" fill="#3a7"/>'
        '<circle cx="60" cy="40" r="25" fill="#fff"/></svg>', encoding="utf-8")

    # Documents
    md = folder / "notes.md"
    md.write_text("# Notes\n\nSome **bold** text and a list:\n\n- one\n- two\n\n"
                  "| a | b |\n|---|---|\n| 1 | 2 |\n\n![picture](picture.png)\n\n"
                  "Ünïcödé ✓ — 你好\n", encoding="utf-8")
    keep(md)
    (keep(folder / "readme.txt")).write_text("Plain text file.\n\nSecond paragraph <with> & symbols.\n",
                                             encoding="utf-8")
    (keep(folder / "page.html")).write_text(
        "<html><head><title>Page</title></head><body><h1>Hello</h1><p>Web <em>page</em>.</p>"
        "<img src='picture.png'></body></html>", encoding="utf-8")
    if pandoc_path():
        for ext in ("docx", "odt", "rtf", "epub", "pptx"):
            subprocess.run([pandoc_path(), str(md), "-o", str(folder / f"document.{ext}"),
                            "--resource-path", str(folder), "-M", "title=Sample"], check=True)
            keep(folder / f"document.{ext}")
    import pymupdf
    doc = pymupdf.open()
    for n in range(2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Sample PDF page {n + 1}", fontsize=18)
        page.insert_text((72, 110), "Converted by the File Converter test suite.", fontsize=11)
        page.insert_image(pymupdf.Rect(72, 140, 272, 265), filename=str(folder / "photo.jpg"))
    doc.save(keep(folder / "document.pdf"))

    # Spreadsheets and data
    (keep(folder / "table.csv")).write_text("zip,name,amount\n00501,Holtsville,12.5\n10001,New York,7\n",
                                            encoding="utf-8")
    import pandas as pd
    with pd.ExcelWriter(keep(folder / "book.xlsx")) as writer:
        pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]}).to_excel(writer, sheet_name="First", index=False)
        pd.DataFrame({"z": [9.5, 8.25]}).to_excel(writer, sheet_name="Second", index=False)
    (keep(folder / "records.json")).write_text(json.dumps(
        [{"id": 1, "name": "Ada", "tags": {"lang": "en"}}, {"id": 2, "name": "Linus", "tags": {"lang": "fi"}}]))
    (keep(folder / "config.yaml")).write_text("name: demo\nport: 8080\nitems:\n  - a\n  - b\n")
    (keep(folder / "settings.toml")).write_text('title = "demo"\n[server]\nport = 8080\n')

    # Media
    if ffmpeg_path():
        ff = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y"]
        subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=2",
                             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                             str(folder / "clip.mp4")], check=True)
        keep(folder / "clip.mp4")
        subprocess.run(ff + ["-i", str(folder / "clip.mp4"), "-c", "copy", str(folder / "movie.mkv")],
                       check=True)
        keep(folder / "movie.mkv")
        subprocess.run(ff + ["-f", "lavfi", "-i", "sine=frequency=330:duration=2", str(folder / "tone.wav")],
                       check=True)
        keep(folder / "tone.wav")
        subprocess.run(ff + ["-i", str(folder / "tone.wav"), str(folder / "song.mp3")], check=True)
        keep(folder / "song.mp3")
        (keep(folder / "captions.srt")).write_text(
            "1\n00:00:00,000 --> 00:00:01,500\nHello there\n\n2\n00:00:01,600 --> 00:00:03,000\nBye\n",
            encoding="utf-8")

    # Archives
    with zipfile.ZipFile(keep(folder / "bundle.zip"), "w") as zf:
        zf.writestr("a.txt", "alpha")
        zf.writestr("sub/b.txt", "beta")

    # Fonts
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf",
                      "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if Path(candidate).exists():
            shutil.copy(candidate, keep(folder / "font.ttf"))
            break
    return made


def check_output(path: Path):
    """Basic sanity checks that the result is a real file of that type."""
    assert path.exists(), f"{path} missing"
    if path.is_dir():
        files = list(path.rglob("*"))
        assert files, f"{path} is an empty folder"
        return
    assert path.stat().st_size > 0, f"{path} is empty"
    ext = path.suffix.lower().lstrip(".")
    if ext in ("png", "jpg", "webp", "gif", "bmp", "tiff", "ico", "heic", "avif"):
        from PIL import Image
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        with Image.open(path) as im:
            im.load()
    elif ext == "pdf":
        import pymupdf
        assert pymupdf.open(path).page_count >= 1
    elif ext in ("docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "zip"):
        with zipfile.ZipFile(path) as zf:
            assert zf.testzip() is None
    elif ext == "json":
        json.loads(path.read_text(encoding="utf-8"))
    elif ext in ("mp4", "mkv", "mov", "webm", "avi", "mp3", "wav", "flac", "m4a", "ogg", "opus"):
        out = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(path)], capture_output=True,
                             text=True).stderr
        assert "Duration" in out, f"ffmpeg can't read {path.name}"


def run_all(verbose=True):
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        samples = make_samples(tmp / "samples")
        for sample in samples:
            for target in targets_for(sample):
                out_dir = tmp / "out" / f"{sample.name}-to-{target}"
                start = time.time()
                try:
                    outputs = convert(sample, target, out_dir, "balanced")
                    for out in outputs:
                        check_output(out)
                    status, detail = "ok", ", ".join(o.name for o in outputs)
                except (ConversionError, AssertionError, Exception) as exc:
                    status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
                results.append((sample.name, target, status, detail, time.time() - start))
                if verbose:
                    print(f"{status:4}  {sample.name:<16} -> {target:<8} {time.time() - start:5.1f}s  {detail[:110]}")
    return results


def test_every_conversion():
    failures = [r for r in run_all(verbose=False) if r[2] != "ok"]
    assert not failures, "\n".join(f"{s} -> {t}: {d}" for s, t, _, d, _ in failures)


def test_bad_input_gives_clear_error(tmp_path):
    fake = tmp_path / "broken.png"
    fake.write_bytes(b"not really an image")
    try:
        convert(fake, "jpg", tmp_path)
    except ConversionError as exc:
        assert "Couldn't read" in str(exc)
    else:
        raise AssertionError("expected a ConversionError")
    assert not (tmp_path / "broken.jpg").exists()


def test_existing_files_are_not_overwritten(tmp_path):
    from PIL import Image
    src = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(src)
    first = convert(src, "jpg", tmp_path)[0]
    second = convert(src, "jpg", tmp_path)[0]
    assert first.name == "a.jpg" and second.name == "a (1).jpg"


if __name__ == "__main__":
    rows = run_all()
    bad = [r for r in rows if r[2] != "ok"]
    print(f"\n{len(rows) - len(bad)}/{len(rows)} conversions passed.")
    sys.exit(1 if bad else 0)
