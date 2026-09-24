"""PDF files: to Word (pdf2docx), to text, to images (PyMuPDF), and on to other
document formats by way of Word."""

import logging
import tempfile
from pathlib import Path

from .engine import Converter
from .tools import ConversionError, has_module, pandoc_path

log = logging.getLogger("converter")

PAGE_IMAGES = {"png", "jpg", "tiff", "webp"}
VIA_WORD = {"odt", "rtf", "html", "md", "epub"}


def _open_pdf(path):
    import pymupdf

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ConversionError(f"Couldn't open this PDF ({exc}).") from exc
    if doc.needs_pass:
        raise ConversionError("This PDF is password-protected. Remove the password first.")
    if doc.page_count == 0:
        raise ConversionError("This PDF has no pages.")
    return doc


def render_pages(pdf_path, job):
    """Save every page as an image. One page -> one file; more -> a folder."""
    from PIL import Image

    doc = _open_pdf(pdf_path)
    dpi = job.pick(300, 200, 110)
    fmt = {"jpg": "JPEG", "png": "PNG", "tiff": "TIFF", "webp": "WEBP"}[job.target]
    opts = {"JPEG": {"quality": job.pick(95, 88, 72)}, "WEBP": {"quality": job.pick(95, 85, 70)},
            "TIFF": {"compression": "tiff_lzw"}, "PNG": {}}[fmt]

    def pages():
        for i, page in enumerate(doc):
            job.check_cancel()
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            job.progress((i + 1) / doc.page_count)

    if doc.page_count > 1 and job.target != "tiff":
        folder = job.work_dir / f"{job.stem}_pages"
        folder.mkdir()
        for i, img in enumerate(pages()):
            img.save(folder / f"{job.stem}-p{i + 1:03d}.{job.target}", fmt, dpi=(dpi, dpi), **opts)
        return [folder]

    # A single image, or one multi-page TIFF (pages are rendered as they're written).
    it = pages()
    first = next(it)
    out = job.out()
    first.save(out, fmt, save_all=doc.page_count > 1, append_images=it, dpi=(dpi, dpi), **opts)
    return [out]


def pdf_to_docx(src, dest, job):
    from pdf2docx import Converter as Pdf2Docx

    _open_pdf(src)  # clear errors for locked/empty files
    logging.getLogger("pdf2docx").setLevel(logging.WARNING)
    try:
        cv = Pdf2Docx(str(src))
        try:
            cv.convert(str(dest))
        finally:
            cv.close()
    except ConversionError:
        raise
    except Exception as exc:
        log.exception("pdf2docx failed")
        raise ConversionError(f"Couldn't rebuild this PDF as a Word document ({exc}).") from exc


class PdfConverter(Converter):
    name = "pdf"

    def available(self):
        return has_module("pymupdf")

    def targets(self, ext, path):
        if ext != "pdf":
            return set()
        out = {"txt"} | (PAGE_IMAGES if has_module("PIL") else set())
        if has_module("pdf2docx"):
            out.add("docx")
            if pandoc_path():
                out |= VIA_WORD
        return out

    def convert(self, job):
        t = job.target
        if t in PAGE_IMAGES:
            return render_pages(job.src, job)
        if t == "txt":
            doc = _open_pdf(job.src)
            parts = []
            for i, page in enumerate(doc):
                job.check_cancel()
                parts.append(page.get_text("text", sort=True).rstrip())
                job.progress((i + 1) / doc.page_count)
            text = "\n\n\f".join(parts).strip()
            if not text:
                raise ConversionError("No text found. This PDF is probably scanned images; "
                                      "try converting it to PNG instead.")
            out = job.out()
            out.write_text(text + "\n", encoding="utf-8")
            return [out]
        if t == "docx":
            out = job.out()
            pdf_to_docx(job.src, out, job)
            return [out]

        # Everything else: PDF -> Word -> pandoc.
        from .documents import pandoc_write

        with tempfile.TemporaryDirectory(prefix="pdf-") as tmp:
            docx = Path(tmp) / "input.docx"
            pdf_to_docx(job.src, docx, job)
            job.check_cancel()
            return pandoc_write(job, docx, "docx")
