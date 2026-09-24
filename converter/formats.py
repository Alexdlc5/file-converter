"""File-type names, labels and extension handling."""

from pathlib import Path

# Extensions made of two parts, checked before the plain suffix.
COMPOUND_EXTS = ("tar.gz", "tar.bz2", "tar.xz")

# Other spellings of the same format, mapped to the name used everywhere else.
ALIASES = {
    "jpeg": "jpg", "jpe": "jpg", "jfif": "jpg",
    "tif": "tiff",
    "heif": "heic",
    "htm": "html", "xhtml": "html",
    "markdown": "md", "mdown": "md", "mkd": "md",
    "latex": "tex",
    "text": "txt", "log": "txt",
    "yml": "yaml",
    "tgz": "tar.gz", "tbz2": "tar.bz2", "tbz": "tar.bz2", "txz": "tar.xz",
    "mpeg": "mpg", "mpe": "mpg",
    "aif": "aiff", "aifc": "aiff",
    "oga": "ogg",
    "qt": "mov",
    "ppsx": "pptx", "pps": "ppt",
    "dotx": "docx", "dot": "doc",
}

# name -> (label, category). Categories order the "Convert to" menus.
FORMATS = {
    # Documents
    "pdf": ("PDF document", "Documents"),
    "docx": ("Word document", "Documents"),
    "doc": ("Word 97-2003 document", "Documents"),
    "odt": ("OpenDocument text", "Documents"),
    "rtf": ("Rich Text", "Documents"),
    "txt": ("Plain text", "Documents"),
    "md": ("Markdown", "Documents"),
    "html": ("Web page (HTML)", "Documents"),
    "epub": ("EPUB e-book", "Documents"),
    "tex": ("LaTeX", "Documents"),
    "rst": ("reStructuredText", "Documents"),
    "org": ("Org mode", "Documents"),
    "ipynb": ("Jupyter notebook", "Documents"),
    "fb2": ("FictionBook e-book", "Documents"),
    "wpd": ("WordPerfect document", "Documents"),
    # Presentations
    "pptx": ("PowerPoint presentation", "Presentations"),
    "ppt": ("PowerPoint 97-2003 presentation", "Presentations"),
    "odp": ("OpenDocument presentation", "Presentations"),
    # Spreadsheets and data
    "xlsx": ("Excel workbook", "Spreadsheets & data"),
    "xlsm": ("Excel macro workbook", "Spreadsheets & data"),
    "xls": ("Excel 97-2003 workbook", "Spreadsheets & data"),
    "ods": ("OpenDocument spreadsheet", "Spreadsheets & data"),
    "csv": ("CSV (comma-separated)", "Spreadsheets & data"),
    "tsv": ("TSV (tab-separated)", "Spreadsheets & data"),
    "json": ("JSON", "Spreadsheets & data"),
    "yaml": ("YAML", "Spreadsheets & data"),
    "toml": ("TOML", "Spreadsheets & data"),
    # Images
    "png": ("PNG image", "Images"),
    "jpg": ("JPEG image", "Images"),
    "webp": ("WebP image", "Images"),
    "gif": ("GIF image", "Images"),
    "bmp": ("Bitmap image", "Images"),
    "tiff": ("TIFF image", "Images"),
    "ico": ("Windows icon", "Images"),
    "heic": ("HEIC image (iPhone)", "Images"),
    "avif": ("AVIF image", "Images"),
    "svg": ("SVG vector image", "Images"),
    "tga": ("Targa image", "Images"),
    "psd": ("Photoshop image", "Images"),
    "icns": ("macOS icon", "Images"),
    "jp2": ("JPEG 2000 image", "Images"),
    "pcx": ("PCX image", "Images"),
    "ppm": ("PPM image", "Images"),
    "pgm": ("PGM image", "Images"),
    "pbm": ("PBM image", "Images"),
    "pnm": ("PNM image", "Images"),
    "dds": ("DirectDraw surface", "Images"),
    # Video
    "mp4": ("MP4 video", "Video"),
    "mkv": ("MKV video", "Video"),
    "mov": ("QuickTime video", "Video"),
    "avi": ("AVI video", "Video"),
    "webm": ("WebM video", "Video"),
    "wmv": ("Windows Media video", "Video"),
    "flv": ("Flash video", "Video"),
    "m4v": ("M4V video", "Video"),
    "mpg": ("MPEG video", "Video"),
    "ogv": ("Ogg video", "Video"),
    "3gp": ("3GP phone video", "Video"),
    "ts": ("MPEG transport stream", "Video"),
    "mts": ("AVCHD video", "Video"),
    "m2ts": ("Blu-ray video", "Video"),
    "vob": ("DVD video", "Video"),
    # Audio
    "mp3": ("MP3 audio", "Audio"),
    "wav": ("WAV audio", "Audio"),
    "flac": ("FLAC lossless audio", "Audio"),
    "m4a": ("M4A audio (AAC)", "Audio"),
    "aac": ("AAC audio", "Audio"),
    "ogg": ("Ogg Vorbis audio", "Audio"),
    "opus": ("Opus audio", "Audio"),
    "wma": ("Windows Media audio", "Audio"),
    "aiff": ("AIFF audio", "Audio"),
    "amr": ("AMR voice audio", "Audio"),
    "ac3": ("Dolby AC-3 audio", "Audio"),
    "mka": ("Matroska audio", "Audio"),
    "caf": ("Core Audio file", "Audio"),
    # Subtitles
    "srt": ("SubRip subtitles", "Subtitles"),
    "vtt": ("WebVTT subtitles", "Subtitles"),
    "ass": ("Advanced SubStation subtitles", "Subtitles"),
    "ssa": ("SubStation subtitles", "Subtitles"),
    # Archives
    "zip": ("ZIP archive", "Archives"),
    "tar": ("TAR archive", "Archives"),
    "tar.gz": ("TAR.GZ archive", "Archives"),
    "tar.bz2": ("TAR.BZ2 archive", "Archives"),
    "tar.xz": ("TAR.XZ archive", "Archives"),
    # Fonts
    "ttf": ("TrueType font", "Fonts"),
    "otf": ("OpenType font", "Fonts"),
    "woff": ("WOFF web font", "Fonts"),
    "woff2": ("WOFF2 web font", "Fonts"),
}

CATEGORY_ORDER = [
    "Documents", "Presentations", "Spreadsheets & data", "Images",
    "Video", "Audio", "Subtitles", "Archives", "Fonts",
]


def raw_ext(path) -> str:
    """The file's extension as written (lower case, no dot); '' if none."""
    name = Path(path).name.lower()
    for ext in COMPOUND_EXTS:
        if name.endswith("." + ext):
            return ext
    return Path(name).suffix[1:]


def get_ext(path) -> str:
    """The file's format name, with aliases resolved (photo.JPEG -> 'jpg')."""
    ext = raw_ext(path)
    return ALIASES.get(ext, ext)


def stem(path) -> str:
    """File name without its extension (archive.tar.gz -> 'archive')."""
    name = Path(path).name
    ext = raw_ext(path)
    return name[: -(len(ext) + 1)] if ext else name


def label(fmt: str) -> str:
    """'pdf' -> 'PDF document (.pdf)'."""
    text = FORMATS.get(fmt, (fmt.upper() + " file", ""))[0]
    return f"{text} (.{fmt})"


def category(fmt: str) -> str:
    return FORMATS.get(fmt, ("", "Other"))[1]


def sort_formats(fmts):
    """Group by category, then keep a sensible order inside each group."""
    order = {name: i for i, name in enumerate(FORMATS)}
    cats = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(fmts, key=lambda f: (cats.get(category(f), 99), order.get(f, 999), f))
