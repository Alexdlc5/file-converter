"""Video, audio and subtitles, using ffmpeg."""

import logging
import re
import subprocess
import tempfile
import threading

from .engine import Converter
from .tools import (NO_WINDOW, Cancelled, ConversionError, ffmpeg_encoders, ffmpeg_path,
                    last_lines, run)

log = logging.getLogger("converter")

VIDEO_IN = {"mp4", "m4v", "mkv", "mov", "avi", "webm", "wmv", "flv", "mpg", "ogv", "3gp",
            "ts", "mts", "m2ts", "vob"}
AUDIO_IN = {"mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma", "aiff", "amr", "ac3",
            "mka", "caf"}
SUBS = {"srt", "vtt", "ass", "ssa"}

# target -> (video encoder, audio encoder, extra args)
VIDEO_OUT = {
    "mp4": ("libx264", "aac", ["-movflags", "+faststart"]),
    "m4v": ("libx264", "aac", ["-movflags", "+faststart", "-f", "mp4"]),
    "mov": ("libx264", "aac", ["-movflags", "+faststart"]),
    "mkv": ("libx264", "aac", []),
    "webm": ("libvpx-vp9", "libopus", []),
    "avi": ("mpeg4", "libmp3lame", ["-vtag", "xvid"]),
    "wmv": ("wmv2", "wmav2", []),
    "flv": ("libx264", "aac", []),
    "mpg": ("mpeg2video", "mp2", ["-f", "mpeg"]),
    "ogv": ("libtheora", "libvorbis", []),
}
# target -> (audio encoder, extra args)
AUDIO_OUT = {
    "mp3": ("libmp3lame", []),
    "wav": ("pcm_s16le", []),
    "flac": ("flac", []),
    "m4a": ("aac", ["-movflags", "+faststart"]),
    "aac": ("aac", ["-f", "adts"]),
    "ogg": ("libvorbis", []),
    "opus": ("libopus", []),
    "wma": ("wmav2", []),
    "aiff": ("pcm_s16be", []),
}
GIF_TO_VIDEO = {"mp4", "webm", "mov"}

# Codecs that can be copied into a container untouched (fast, lossless "remux").
COPY_OK = {
    "mp4": ({"h264", "hevc"}, {"aac", "mp3", None}),
    "m4v": ({"h264", "hevc"}, {"aac", None}),
    "mov": ({"h264", "hevc"}, {"aac", "mp3", None}),
    "mkv": (None, None),  # Matroska holds anything
    "webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis", None}),
}
AUDIO_COPY = {"mp3": "mp3", "m4a": "aac", "aac": "aac", "flac": "flac", "opus": "opus", "ogg": "vorbis"}


def _video_quality(enc, q):
    i = {"best": 0, "balanced": 1, "small": 2}[q]
    if enc == "libx264":
        return ["-crf", ("18", "23", "28")[i], "-preset", "medium", "-pix_fmt", "yuv420p"]
    if enc == "libvpx-vp9":
        return ["-crf", ("28", "33", "38")[i], "-b:v", "0", "-row-mt", "1",
                "-deadline", "good", "-cpu-used", ("2", "4", "5")[i], "-pix_fmt", "yuv420p"]
    if enc in ("mpeg4", "wmv2", "mpeg2video"):
        return ["-q:v", ("2", "4", "7")[i]]
    if enc == "libtheora":
        return ["-q:v", ("9", "7", "5")[i]]
    return []


def _audio_quality(enc, q):
    i = {"best": 0, "balanced": 1, "small": 2}[q]
    return {
        "aac": ["-b:a", ("256k", "192k", "128k")[i]],
        "libmp3lame": ["-q:a", ("0", "2", "5")[i]],
        "libopus": ["-b:a", ("192k", "128k", "96k")[i]],
        "libvorbis": ["-q:a", ("8", "5", "3")[i]],
        "wmav2": ["-b:a", ("192k", "160k", "128k")[i]],
        "mp2": ["-b:a", ("384k", "256k", "192k")[i]],
    }.get(enc, [])


def probe(path):
    """Duration (seconds) and stream codecs, read from ffmpeg's own report."""
    proc = subprocess.run([ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(path)],
                          capture_output=True, stdin=subprocess.DEVNULL,
                          creationflags=NO_WINDOW, timeout=60)
    text = proc.stderr.decode("utf-8", "replace")
    info = {"duration": None, "video": [], "audio": [], "subtitle": []}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        h, mnt, s = m.groups()
        info["duration"] = int(h) * 3600 + int(mnt) * 60 + float(s)
    for kind, codec, rest in re.findall(r"Stream #\S+.*?: (Video|Audio|Subtitle): (\w+)(.*)", text):
        if kind == "Video" and "attached pic" in rest:
            continue  # album art, not real video
        info[kind.lower()].append(codec)
    if "Invalid data found" in text or ("Duration" not in text and not info["audio"] and not info["video"]):
        raise ConversionError("ffmpeg can't read this file. It may be damaged or not really a media file.")
    return info


def _looks_like_mpegts(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(189)
        return len(head) == 189 and head[0] == 0x47 and head[188] == 0x47
    except OSError:
        return False


class MediaConverter(Converter):
    name = "media"

    def available(self):
        return bool(ffmpeg_path())

    def targets(self, ext, path):
        enc = ffmpeg_encoders()
        if ext == "ts" and not _looks_like_mpegts(path):
            return set()  # probably a TypeScript file
        audio = {t for t, (a, _) in AUDIO_OUT.items() if a in enc}
        video = {t for t, (v, a, _) in VIDEO_OUT.items() if v in enc and a in enc}
        if ext in VIDEO_IN:
            return video | audio | ({"gif"} if "gif" in enc else set())
        if ext in AUDIO_IN:
            return audio
        if ext == "gif":
            return video & GIF_TO_VIDEO
        return set()

    def convert(self, job):
        info = probe(job.src)
        out = job.out()
        t = job.target
        base = [ffmpeg_path(), "-hide_banner", "-nostdin", "-y", "-i", str(job.src)]

        if t in AUDIO_OUT:
            if not info["audio"]:
                raise ConversionError("This file has no sound to convert.")
            enc, extra = AUDIO_OUT[t]
            src_codec = info["audio"][0]
            if job.quality != "small" and AUDIO_COPY.get(t) == src_codec:
                try:
                    _ffmpeg(base + ["-map", "0:a:0", "-vn", "-sn", "-dn", "-c:a", "copy"] + extra + [out],
                            job, info["duration"])
                    return [out]
                except ConversionError:
                    log.info("audio copy failed, re-encoding")
            _ffmpeg(base + ["-map", "0:a:0", "-vn", "-sn", "-dn", "-c:a", enc]
                    + _audio_quality(enc, job.quality) + extra + [out], job, info["duration"])
            return [out]

        if not info["video"]:
            raise ConversionError("This file has no video picture to convert.")

        if t == "gif":
            fps, width = job.pick(("15", "960"), ("12", "640"), ("10", "480"))
            graph = (f"fps={fps},scale='min({width},iw)':-1:flags=lanczos,split[a][b];"
                     "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
            _ffmpeg(base + ["-map", "0:V:0", "-an", "-vf", graph, "-loop", "0", out],
                    job, info["duration"])
            return [out]

        venc, aenc, extra = VIDEO_OUT[t]
        maps = ["-map", "0:V:0"]
        if job.src_ext != "gif":
            maps += ["-map", "0:a?"] if t in ("mkv", "mp4", "mov", "webm", "m4v") else ["-map", "0:a:0?"]

        if job.quality != "small" and t in COPY_OK:
            vok, aok = COPY_OK[t]
            v = info["video"][0]
            audio = info["audio"] or [None]
            if (vok is None or v in vok) and (aok is None or all(a in aok for a in audio)):
                copy = base + maps + ["-c", "copy"]
                if t == "mkv":
                    copy += ["-map", "0:s?"]
                if v == "hevc" and t in ("mp4", "mov", "m4v"):
                    copy += ["-tag:v", "hvc1"]
                try:
                    _ffmpeg(copy + extra + [out], job, info["duration"])
                    return [out]
                except ConversionError:
                    log.info("remux failed, re-encoding")

        cmd = base + maps + ["-c:v", venc] + _video_quality(venc, job.quality)
        cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
        if info["audio"] and job.src_ext != "gif":
            cmd += ["-c:a", aenc] + _audio_quality(aenc, job.quality)
            if aenc in ("wmav2", "mp2", "libmp3lame"):
                cmd += ["-ac", "2"]
        cmd += ["-sn", "-dn"] + extra + [out]
        _ffmpeg(cmd, job, info["duration"])
        return [out]


def _ffmpeg(cmd, job, duration):
    """Run ffmpeg, reporting progress and honouring Cancel."""
    cmd = [str(c) for c in cmd]
    cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]
    log.info("run: %s", " ".join(cmd))
    with tempfile.TemporaryFile() as errfile:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errfile,
                                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        stop = threading.Event()

        def watch_cancel():
            while not stop.wait(0.25):
                if job.cancel.is_set():
                    proc.kill()
                    return

        threading.Thread(target=watch_cancel, daemon=True).start()
        try:
            for raw in proc.stdout:
                line = raw.decode("ascii", "replace").strip()
                if duration and (line.startswith("out_time_us=") or line.startswith("out_time_ms=")):
                    try:
                        job.progress(min(1.0, int(line.split("=", 1)[1]) / 1e6 / duration))
                    except ValueError:
                        pass
            proc.wait()
        finally:
            stop.set()
        if job.cancel.is_set():
            raise Cancelled()
        if proc.returncode != 0:
            errfile.seek(0)
            err = errfile.read().decode("utf-8", "replace")
            log.warning("ffmpeg failed: %s", err[-3000:])
            raise ConversionError(_explain(err))


def _explain(err):
    if "No space left" in err:
        return "The disk is full."
    if "Permission denied" in err:
        return "Permission denied writing the output."
    lines = [l for l in err.splitlines() if l.strip() and not l.startswith(("  ", "Input", "Output", "Stream"))]
    return last_lines("\n".join(lines), 2) or "ffmpeg failed."


class SubtitleConverter(Converter):
    name = "subtitles"

    def available(self):
        return bool(ffmpeg_path())

    def targets(self, ext, path):
        enc = ffmpeg_encoders()
        codecs = {"srt": "srt", "vtt": "webvtt", "ass": "ass", "ssa": "ssa"}
        return {t for t, c in codecs.items() if c in enc} if ext in SUBS else set()

    def convert(self, job):
        out = job.out()
        run([ffmpeg_path(), "-hide_banner", "-nostdin", "-y", "-i", job.src, out], job.cancel, 120)
        return [out]
