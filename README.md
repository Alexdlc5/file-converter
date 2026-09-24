# File Converter

A desktop app built using Claude Opus 5.5 that converts files from one format to another. Drop in documents, PDFs, images, video, audio, spreadsheets and more, pick an output format for each type, and click **Convert**. It all runs on your computer, and no files are uploaded anywhere.

Works on Windows 10/11, macOS and Linux.

## Install (one time)

1. Get this folder onto your computer. On GitHub, click **Code → Download ZIP**, unzip it, and move the `file-converter` folder somewhere permanent, such as Documents. The desktop shortcut runs the app from this folder, so don't leave it in Downloads if you clean that out.
2. Run the installer for your system:

| System | Double-click | Notes |
|---|---|---|
| Windows | `Install on Windows.bat` | If Python is missing, it installs it with winget and asks you to run the installer again. If SmartScreen warns you, click **More info → Run anyway**. |
| macOS | `Install on Mac.command` | If macOS blocks it, right-click it and choose **Open**. Needs Python from [python.org](https://www.python.org/downloads/). |
| Linux | `install-linux.sh` | Needs `python3`, `python3-venv` and `python3-tk`. |

The installer creates a private Python environment inside the folder. It downloads about 700 MB of converters, including its own copies of ffmpeg and pandoc, and puts a **File Converter** icon on your desktop. Setup takes a few minutes.

**Optional:** install [LibreOffice](https://www.libreoffice.org/download/) (free) to convert PowerPoint files and old `.doc`/`.xls`/`.ppt` files, and to get exact-layout Word/Excel → PDF. The app detects it automatically.

## Use

- Open **File Converter** from the desktop, then drop files (or whole folders) onto the window, or click to browse.
- Each file type in the list gets its own **Convert to** menu, so a mixed batch like photos + a Word doc + a video converts in one go.
- **Quality**: *Best*, *Balanced* or *Smaller files*. This applies to JPEG/WebP/HEIC images, video, audio and PDF page images.
- **Save to**: next to each original (default) or into a folder you choose. Existing files are never overwritten; new ones get names like `photo (1).jpg`.
- Double-click a finished row to open the result. Double-click a failed (red) row to see why it failed.

Shortcuts:
- **Windows:** drop files straight onto the desktop icon, or right-click any file → **Send to → File Converter**.
- **macOS:** drop files onto the app icon.

## What converts to what

| From | To |
|---|---|
| **Word, OpenDocument, RTF** (docx, odt, rtf) | pdf, docx, odt, rtf, txt, md, html, epub, tex, rst, org. With LibreOffice, also doc |
| **Markdown, HTML, text, EPUB, LaTeX, reST, Org, Jupyter, FB2** | pdf, docx, odt, rtf, txt, md, html, epub, tex, rst, org |
| **PDF** | docx, odt, rtf, txt, md, html, epub, png, jpg, webp, tiff (one image per page) |
| **PowerPoint** (pptx, ppt, odp), needs LibreOffice | pdf, pptx, odp, ppt, png, jpg |
| **Old Word** (doc, wpd), needs LibreOffice | pdf, docx, odt, rtf |
| **Excel, OpenDocument** (xlsx, xls, ods) | csv, tsv, xlsx, ods, json, html, md, txt, pdf. With LibreOffice, also xls |
| **CSV / TSV / JSON** | csv, tsv, xlsx, ods, json, html, md, txt, pdf |
| **JSON / YAML / TOML** | json, yaml, toml |
| **Images** (png, jpg, webp, gif, bmp, tiff, ico, heic, avif, psd, tga, jp2, icns, …) | png, jpg, webp, gif, bmp, tiff, ico, pdf, heic, avif |
| **SVG** | png, jpg, webp, pdf |
| **Animated GIF** | mp4, webm, mov, plus all the image formats (animation is kept in webp and png) |
| **Video** (mp4, mkv, mov, avi, webm, wmv, flv, m4v, mpg, 3gp, ts, mts, vob, ogv) | mp4, mkv, mov, avi, webm, wmv, flv, m4v, mpg, ogv, gif, and any audio format (extracts the sound) |
| **Audio** (mp3, wav, flac, m4a, aac, ogg, opus, wma, aiff, amr, ac3, …) | mp3, wav, flac, m4a, aac, ogg, opus, wma, aiff |
| **Subtitles** (srt, vtt, ass, ssa) | srt, vtt, ass, ssa |
| **Archives** (zip, tar, tar.gz, tar.bz2, tar.xz) | any of the others |
| **Fonts** (ttf, otf, woff, woff2) | woff, woff2, and back to ttf/otf |

The app only offers conversions that make sense for each file. A few details:

- Converting between MKV, MP4 and MOV copies the video without re-encoding when the codecs allow it. That's near-instant and lossless.
- A spreadsheet with several sheets turned into CSV becomes a folder with one CSV per sheet.
- A multi-page PDF turned into images becomes a folder with one image per page.
- Documents turned into Markdown keep their images in a `<name>_files` folder next to the result.
- Scanned PDFs are pictures of text. Converting them to text or Word won't find any words (there's no OCR).

## Command line

```
.venv/bin/python file_converter.py --to pdf report.docx notes.md     # Windows: .venv\Scripts\python
.venv/bin/python file_converter.py --to mp3 --quality best --out ~/Music video.mov
.venv/bin/python file_converter.py --formats photo.heic               # what can this become?
.venv/bin/python file_converter.py --check                           # which converters are ready?
```

## Troubleshooting

- **A file type says "not supported"**: select the row to see a hint. It's usually "install LibreOffice".
- **Something failed**: double-click the red row for the reason. A detailed log is kept at `%APPDATA%\FileConverter\file-converter.log` (Windows), `~/Library/Application Support/FileConverter/` (macOS) or `~/.config/file-converter/` (Linux).
- **Repair or update**: run the installer again.
- **Uninstall**: run `python install.py --uninstall` in this folder, which removes the shortcuts and the private environment. Then delete the folder.

## For developers

```
python tests/test_conversions.py     # makes a sample of every type and runs every conversion
```

The code is in `converter/`. `engine.py` picks a converter for each file. Each of `images.py`, `media.py`, `documents.py`, `pdfs.py`, `data.py`, `archives.py` and `fonts.py` declares what it reads and writes. `gui.py` is the window.
