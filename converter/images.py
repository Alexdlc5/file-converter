"""Images, using Pillow (plus pillow-heif for iPhone photos and PyMuPDF for SVG)."""

from .engine import Converter
from .tools import ConversionError, has_module

READ = {"png", "jpg", "webp", "gif", "bmp", "tiff", "ico", "heic", "avif", "tga", "psd",
        "icns", "jp2", "pcx", "ppm", "pgm", "pbm", "pnm", "dds", "svg"}
WRITE = {"png", "jpg", "webp", "gif", "bmp", "tiff", "ico", "pdf", "heic", "avif"}
ANIMATED = {"gif", "webp", "png"}
NO_ALPHA = {"jpg", "bmp", "pdf"}
PIL_FORMAT = {"jpg": "JPEG", "tiff": "TIFF", "heic": "HEIF", "ico": "ICO", "bmp": "BMP",
              "png": "PNG", "webp": "WEBP", "gif": "GIF", "pdf": "PDF", "avif": "AVIF"}

_heif_ready = False


def _register_heif():
    global _heif_ready
    if not _heif_ready and has_module("pillow_heif"):
        import pillow_heif
        pillow_heif.register_heif_opener()
        _heif_ready = True
    return _heif_ready


def _avif_ok():
    from PIL import features
    try:
        return bool(features.check("avif"))
    except Exception:
        return False


class ImageConverter(Converter):
    name = "images"

    def available(self):
        return has_module("PIL")

    def targets(self, ext, path):
        if ext not in READ:
            return set()
        if ext == "svg":
            return {"png", "jpg", "webp", "pdf"} if has_module("pymupdf") else set()
        if ext == "heic" and not has_module("pillow_heif"):
            return set()
        out = set(WRITE)
        if not has_module("pillow_heif"):
            out.discard("heic")
        if not _avif_ok():
            out.discard("avif")
        return out

    def convert(self, job):
        if job.src_ext == "svg":
            return self._from_svg(job)
        from PIL import Image, ImageOps, ImageSequence

        _register_heif()
        Image.MAX_IMAGE_PIXELS = 400_000_000  # allow big scans/panoramas
        try:
            img = Image.open(job.src)
            img.load()
        except Exception as exc:
            raise ConversionError(f"Couldn't read this image ({exc}).") from exc

        target = job.target
        out = job.out()
        frames = getattr(img, "n_frames", 1)
        animated = getattr(img, "is_animated", False) and frames > 1

        if animated and target in ANIMATED:
            seq = [_fix_mode(f.copy(), target) for f in ImageSequence.Iterator(img)]
            durations = [f.info.get("duration", img.info.get("duration", 100)) or 100
                         for f in ImageSequence.Iterator(img)]
            opts = dict(save_all=True, append_images=seq[1:], duration=durations,
                        loop=img.info.get("loop", 0))
            if target == "gif":
                opts["disposal"] = 2
            if target == "webp":
                opts["quality"] = job.pick(95, 85, 70)
            seq[0].save(out, PIL_FORMAT[target], **opts)
            return [out]

        if job.src_ext == "tiff" and frames > 1 and target in ("pdf", "tiff"):
            pages = [_fix_mode(ImageOps.exif_transpose(p.copy()), target)
                     for p in ImageSequence.Iterator(img)]
            pages[0].save(out, PIL_FORMAT[target], save_all=True, append_images=pages[1:],
                          **_save_opts(target, job, img))
            return [out]

        frame = ImageOps.exif_transpose(img)
        if target == "ico":
            frame = _square(_fix_mode(frame, "png"))
            sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= frame.width] or [(16, 16)]
            frame.save(out, "ICO", sizes=sizes)
            return [out]
        frame = _fix_mode(frame, target)
        frame.save(out, PIL_FORMAT[target], **_save_opts(target, job, img, frame))
        return [out]

    def _from_svg(self, job):
        import pymupdf
        from PIL import Image

        try:
            doc = pymupdf.open(job.src)
        except Exception as exc:
            raise ConversionError(f"Couldn't read this SVG ({exc}).") from exc
        out = job.out()
        if job.target == "pdf":
            out.write_bytes(doc.convert_to_pdf())
            return [out]
        page = doc[0]
        longest = max(page.rect.width, page.rect.height, 1)
        # SVGs have no fixed resolution: draw at least 2x, and 1024px on the long side.
        zoom = min(16.0, max(2.0, 1024 / longest))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
        img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
        img = _fix_mode(img, job.target)
        img.save(out, PIL_FORMAT[job.target], **_save_opts(job.target, job, img))
        return [out]


def _fix_mode(img, target):
    """Convert to a pixel format the target can store (flattening transparency if needed)."""
    from PIL import Image

    if img.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N", "F"):
        import numpy as np
        arr = np.asarray(img, dtype="float64")
        top = arr.max() or 1
        img = Image.fromarray((arr / top * 255).clip(0, 255).astype("uint8"), "L")
    if img.mode == "P":
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
    elif img.mode in ("PA", "RGBa", "La", "LA"):
        img = img.convert("RGBA")
    elif img.mode not in ("1", "L", "RGB", "RGBA"):
        img = img.convert("RGB")

    if target in NO_ALPHA and img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        img = background
    if target in ("heic", "avif") and img.mode in ("1", "L"):
        img = img.convert("RGB")
    if target == "jpg" and img.mode == "1":
        img = img.convert("L")
    return img


def _square(img):
    from PIL import Image

    side = max(img.size)
    if img.width == img.height:
        return img
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def _save_opts(target, job, original, frame=None):
    opts = {}
    icc = original.info.get("icc_profile")
    if icc and target in ("jpg", "png", "webp", "tiff", "heic", "avif"):
        opts["icc_profile"] = icc
    exif = None
    if frame is not None and target in ("jpg", "webp", "png", "tiff", "heic", "avif"):
        try:
            data = frame.getexif()
            exif = data.tobytes() if len(data) else None
        except Exception:
            exif = None
    if exif:
        opts["exif"] = exif
    if target == "jpg":
        opts.update(quality=job.pick(95, 88, 72), optimize=True)
        if job.quality == "best":
            opts["subsampling"] = 0
    elif target == "webp":
        opts.update(quality=job.pick(95, 85, 70), method=4)
    elif target == "heic":
        opts.update(quality=job.pick(95, 85, 70))
    elif target == "avif":
        opts.update(quality=job.pick(90, 75, 55))
    elif target == "png":
        opts.update(optimize=job.quality == "small")
    elif target == "tiff":
        opts.update(compression="tiff_lzw")
    elif target == "pdf":
        opts.update(resolution=150.0)
    return opts
