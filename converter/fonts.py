"""Fonts: desktop fonts (TTF/OTF) to and from web fonts (WOFF/WOFF2), using fontTools."""

from .engine import Converter
from .tools import ConversionError, has_module

FONT_IN = {"ttf", "otf", "woff", "woff2"}


def _outline_ext(path):
    """'ttf' for TrueType outlines, 'otf' for PostScript (CFF) outlines."""
    from fontTools.ttLib import TTFont

    try:
        with TTFont(path, lazy=True) as font:
            return "otf" if ("CFF " in font or "CFF2" in font) else "ttf"
    except Exception:
        return None


class FontConverter(Converter):
    name = "fonts"

    def available(self):
        return has_module("fontTools")

    def targets(self, ext, path):
        if ext not in FONT_IN:
            return set()
        out = {"woff"} | ({"woff2"} if has_module("brotli") else set())
        desktop = _outline_ext(path)
        if desktop is None:
            return set()
        out.add(desktop)
        return out

    def convert(self, job):
        from fontTools.ttLib import TTFont

        try:
            font = TTFont(job.src)
        except Exception as exc:
            raise ConversionError(f"Couldn't read this font ({exc}).") from exc
        font.flavor = {"woff": "woff", "woff2": "woff2"}.get(job.target)
        out = job.out()
        font.save(out)
        return [out]
