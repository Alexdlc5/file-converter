"""Documents: pandoc for text formats, LibreOffice (if installed) for Office files."""

import html
import re
import shutil
import tempfile
from pathlib import Path

from .engine import Converter
from .tools import ConversionError, default_paper, has_module, pandoc_path, run, soffice_path

# Our name -> pandoc's reader / writer name.
PANDOC_READ = {"docx": "docx", "odt": "odt", "rtf": "rtf", "md": "markdown", "html": "html",
               "epub": "epub", "tex": "latex", "rst": "rst", "org": "org", "ipynb": "ipynb",
               "fb2": "fb2", "txt": "html"}  # txt is wrapped in HTML first, see _text_as_html
PANDOC_WRITE = {"docx": "docx", "odt": "odt", "rtf": "rtf", "md": "gfm", "html": "html5",
                "epub": "epub3", "tex": "latex", "rst": "rst", "org": "org", "txt": "plain",
                "ipynb": "ipynb"}
STANDALONE = {"html", "rtf", "tex"}
MEDIA_FOLDER = {"md", "rst", "org", "tex"}  # images are saved next to these

WRITER_IN = {"doc", "docx", "odt", "rtf", "wpd"}
CALC_IN = {"xls", "xlsx", "xlsm", "ods"}
IMPRESS_IN = {"ppt", "pptx", "odp"}


def read_text(path) -> str:
    raw = Path(path).read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


def _text_as_html(path) -> str:
    text = read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    body = "\n".join("<p>" + html.escape(p).replace("\n", "<br/>\n") + "</p>" for p in paras)
    return f"<html><head><meta charset='utf-8'></head><body>\n{body}\n</body></html>"


class PandocConverter(Converter):
    name = "pandoc"

    def available(self):
        return bool(pandoc_path())

    def targets(self, ext, path):
        if ext not in PANDOC_READ:
            return set()
        out = set(PANDOC_WRITE) | ({"pdf"} if has_module("pymupdf") else set())
        if ext != "ipynb":
            out.discard("ipynb")
        return out

    def convert(self, job):
        with tempfile.TemporaryDirectory(prefix="pandoc-") as tmp:
            tmp = Path(tmp)
            src, reader = job.src, PANDOC_READ[job.src_ext]
            if job.src_ext == "txt":
                src = tmp / "input.html"
                src.write_text(_text_as_html(job.src), encoding="utf-8")

            if job.target == "pdf":
                return [self._to_pdf(job, src, reader, tmp)]
            return pandoc_write(job, src, reader)

    def _to_pdf(self, job, src, reader, tmp):
        if reader == "html":
            page = read_text(src)
            base = src.parent
        else:
            page = run([pandoc_path(), str(src), "-f", reader, "-t", "html5",
                        "--resource-path", str(job.src.parent), "--extract-media=media"],
                       job.cancel, 600, cwd=tmp)
            base = tmp
        out = job.out()
        html_to_pdf(page, out, [base, job.src.parent], job)
        return out


# Drops picture sizes so Markdown gets plain ![](image.png) instead of HTML <img> tags.
PLAIN_IMAGES_LUA = """
function Image(el)
  el.attributes.width = nil
  el.attributes.height = nil
  el.attributes.style = nil
  return el
end
"""


def pandoc_write(job, src, reader):
    """Convert src with pandoc into job.target; returns the files made."""
    out = job.out()
    t = job.target
    cmd = [pandoc_path(), str(src), "-f", reader, "-t", PANDOC_WRITE[t], "-o", str(out),
           "--resource-path", str(job.src.parent)]
    if t in STANDALONE:
        cmd.append("--standalone")
    if t == "html":
        cmd += ["--embed-resources", "--metadata", f"pagetitle={job.stem}"]
    if t == "txt":
        cmd.append("--wrap=none")
    if t in ("md", "rst", "org"):
        cmd.append("--wrap=preserve")
    outputs = [out]
    if t in MEDIA_FOLDER:
        cmd.append(f"--extract-media={job.stem}_files")
        outputs.append(job.work_dir / f"{job.stem}_files")
    with tempfile.TemporaryDirectory(prefix="lua-") as tmp:
        if t == "md":
            lua = Path(tmp) / "plain-images.lua"
            lua.write_text(PLAIN_IMAGES_LUA, encoding="utf-8")
            cmd += ["--lua-filter", str(lua)]
        run(cmd, job.cancel, 600, cwd=job.work_dir)
    return outputs


BASE_CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.4; }
h1 { font-size: 20pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
pre, code { font-family: monospace; font-size: 9.5pt; }
pre { background-color: #f4f4f4; padding: 6px; }
blockquote { margin-left: 18px; color: #555; }
table { border-collapse: collapse; margin-bottom: 8px; }
th, td { border: 1px solid #999; padding: 3px 6px; }
th { background-color: #eee; }
"""


def html_to_pdf(page, out, folders, job, css=BASE_CSS, landscape=False):
    """Lay out HTML onto PDF pages with PyMuPDF (no browser or LaTeX needed)."""
    import pymupdf

    archive = pymupdf.Archive()
    for folder in folders:
        if folder and Path(folder).is_dir():
            archive.add(str(folder))
    story = pymupdf.Story(html=_limit_images(page, folders), user_css=css, archive=archive)
    rect = pymupdf.paper_rect(default_paper() + ("-l" if landscape else ""))
    frame = rect + (54, 54, -54, -54)  # 0.75 inch margins
    writer = pymupdf.DocumentWriter(str(out))
    more, pages, empty = 1, 0, 0
    try:
        while more:
            job.check_cancel()
            device = writer.begin_page(rect)
            more, filled = story.place(frame)
            story.draw(device)
            writer.end_page()
            pages += 1
            empty = empty + 1 if pymupdf.Rect(filled).is_empty else 0
            if empty > 3 or pages > 5000:
                raise ConversionError("Part of this document is too big to fit on a PDF page.")
    finally:
        writer.close()
    return out


def _limit_images(page, folders):
    """Give each <img> an explicit size that fits the page, since the layout engine
    doesn't shrink big pictures by itself."""
    try:
        from PIL import Image
    except ImportError:
        return page
    max_w, max_h = 480, 620  # points inside the margins

    def fix(match):
        tag = match.group(0)
        src = re.search(r'src\s*=\s*["\']([^"\']+)["\']', tag)
        if not src or re.search(r"\b(width|height)\s*=", tag) or src.group(1).startswith("data:"):
            return tag
        for folder in folders:
            path = Path(folder) / src.group(1)
            if path.is_file():
                try:
                    with Image.open(path) as im:
                        w, h = im.size
                except Exception:
                    return tag
                scale = min(1.0, max_w / w, max_h / h)
                return tag[:-1].rstrip("/") + f' width="{int(w * scale)}" height="{int(h * scale)}">'
        return tag

    return re.sub(r"<img\b[^>]*>", fix, page, flags=re.I)


class LibreOfficeConverter(Converter):
    """Optional. Keeps Word/Excel/PowerPoint layouts intact and opens old .doc/.xls/.ppt."""

    name = "libreoffice"

    def available(self):
        return bool(soffice_path())

    def targets(self, ext, path):
        if ext in WRITER_IN:
            return {"pdf", "docx", "odt", "doc", "rtf"}
        if ext in CALC_IN:
            return {"pdf", "xlsx", "ods", "xls"}
        if ext in IMPRESS_IN:
            out = {"pdf", "pptx", "odp", "ppt"}
            return out | ({"png", "jpg"} if has_module("pymupdf") else set())
        return set()

    def convert(self, job):
        slides_as_images = job.target in ("png", "jpg")
        fmt = "pdf" if slides_as_images else job.target
        with tempfile.TemporaryDirectory(prefix="lo-") as tmp:
            tmp = Path(tmp)
            # A private profile lets this run even while LibreOffice is open.
            profile = Path(tempfile.gettempdir()) / "file-converter-lo-profile"
            # Copy under a plain name: LibreOffice dislikes some characters in paths.
            src = tmp / f"input.{job.src.suffix.lstrip('.') or job.src_ext}"
            shutil.copyfile(job.src, src)
            run([soffice_path(), f"-env:UserInstallation={profile.as_uri()}", "--headless",
                 "--norestore", "--convert-to", fmt, "--outdir", str(tmp / "out"), str(src)],
                job.cancel, 600)
            made = tmp / "out" / f"input.{fmt}"
            if not made.exists():
                raise ConversionError("LibreOffice couldn't convert this file.")
            if slides_as_images:
                from .pdfs import render_pages
                return render_pages(made, job)
            out = job.out()
            shutil.move(str(made), out)
            return [out]

