"""
MediaForge — FFmpeg Operations Module

Standalone module for all FFmpeg-based media processing.
Each function runs FFmpeg as a subprocess and returns the output file path.
All functions check for FFmpeg availability and raise clear errors if missing.

Works with video, audio, and image files.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────────

FFMPEG_WORK_DIR = Path(tempfile.gettempdir()) / "mediaforge_ffmpeg"
FFMPEG_WORK_DIR.mkdir(parents=True, exist_ok=True)

# Supported file extensions by media type
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v", ".ts", ".mts"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav", ".flac", ".wma"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".svg"}
ALL_MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS


# ── Helpers ───────────────────────────────────────────────────────────────────


def _check_ffmpeg() -> str:
    """Check if ffmpeg is available and return its path. Raises RuntimeError if not found."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError(
            "FFmpeg is not installed on this system. "
            "Please install FFmpeg to use media processing features. "
            "See: https://ffmpeg.org/download.html"
        )
    return ffmpeg_path


def _check_ffprobe() -> str:
    """Check if ffprobe is available and return its path."""
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        raise RuntimeError("FFprobe is not installed. It is required for media probing.")
    return ffprobe_path


def _make_output_path(input_path: str | Path, suffix: str = "", ext: str | None = None) -> Path:
    """Generate a unique output path in the work directory."""
    uid = uuid.uuid4().hex[:10]
    input_stem = Path(input_path).stem[:30]
    output_ext = ext or Path(input_path).suffix or ".mp4"
    filename = f"{input_stem}_{suffix}_{uid}{output_ext}" if suffix else f"{input_stem}_{uid}{output_ext}"
    return FFMPEG_WORK_DIR / filename


def _run_ffmpeg(args: list[str], description: str = "FFmpeg operation") -> None:
    """Run an FFmpeg command and raise on failure."""
    ffmpeg = _check_ffmpeg()
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(f"{description} failed: {stderr or 'unknown error'}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{description} timed out after 5 minutes")


def _detect_media_type(file_path: str | Path) -> str:
    """Detect media type from file extension."""
    ext = Path(file_path).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    elif ext in AUDIO_EXTENSIONS:
        return "audio"
    elif ext in IMAGE_EXTENSIONS:
        return "image"
    return "unknown"


def probe(file_path: str | Path) -> dict[str, Any]:
    """
    Probe a media file and return its metadata.

    Returns dict with keys: format, streams, duration, size, bitrate, etc.
    """
    ffprobe = _check_ffprobe()
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"FFprobe failed: {result.stderr.strip()}")
    data = json.loads(result.stdout)

    # Extract useful summary
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    info: dict[str, Any] = {
        "file": str(file_path),
        "filename": Path(file_path).name,
        "media_type": _detect_media_type(file_path),
        "format_name": fmt.get("format_name", ""),
        "format_long_name": fmt.get("format_long_name", ""),
        "duration": float(fmt.get("duration", 0)),
        "size": int(fmt.get("size", 0)),
        "bitrate": int(fmt.get("bit_rate", 0)),
        "streams_count": len(streams),
        "streams": [],
    }

    for s in streams:
        stream_info: dict[str, Any] = {
            "index": s.get("index"),
            "codec_type": s.get("codec_type"),
            "codec_name": s.get("codec_name"),
            "codec_long_name": s.get("codec_long_name", ""),
        }
        if s.get("codec_type") == "video":
            stream_info["width"] = s.get("width")
            stream_info["height"] = s.get("height")
            stream_info["fps"] = eval(s.get("r_frame_rate", "0/1")) if s.get("r_frame_rate") else 0
            stream_info["pix_fmt"] = s.get("pix_fmt", "")
        elif s.get("codec_type") == "audio":
            stream_info["sample_rate"] = int(s.get("sample_rate", 0))
            stream_info["channels"] = s.get("channels")
            stream_info["channel_layout"] = s.get("channel_layout", "")
        info["streams"].append(stream_info)

    return info


# ── Core Operations ───────────────────────────────────────────────────────────


def trim(
    input_path: str | Path,
    start: float,
    end: float,
    output_path: str | Path | None = None,
) -> Path:
    """
    Trim/cut a media file from start to end time (in seconds).

    Works with video, audio. For images, returns the image unchanged.
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type == "image":
        # Images can't be trimmed — just copy
        out = output_path or _make_output_path(input_path, "trimmed")
        shutil.copy2(input_path, out)
        return out

    out = Path(output_path) if output_path else _make_output_path(input_path, "trimmed")
    duration = end - start

    if media_type == "video":
        _run_ffmpeg([
            "-i", str(input_path),
            "-ss", str(start),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out),
        ], f"Trim {start}s-{end}s")
    elif media_type == "audio":
        _run_ffmpeg([
            "-i", str(input_path),
            "-ss", str(start),
            "-t", str(duration),
            "-c:a", "libmp3lame", "-q:a", "2",
            str(out),
        ], f"Trim audio {start}s-{end}s")

    return out


def concatenate(
    input_paths: list[str | Path],
    output_path: str | Path | None = None,
) -> Path:
    """
    Join/concatenate multiple media files of the same type.

    All files must be the same media type (all video or all audio).
    Uses FFmpeg concat demuxer for fast joining without re-encoding
    when codecs match, otherwise re-encodes.
    """
    if not input_paths:
        raise ValueError("At least one input file is required")
    if len(input_paths) == 1:
        # Single file — just copy
        out = Path(output_path) if output_path else _make_output_path(input_paths[0], "joined")
        shutil.copy2(input_paths[0], out)
        return out

    # Verify all files are the same type
    types = {_detect_media_type(p) for p in input_paths}
    if len(types) != 1:
        raise ValueError(f"Cannot concatenate files of different types: {types}")

    media_type = types.pop()
    first = Path(input_paths[0])
    out = Path(output_path) if output_path else _make_output_path(first, "joined")

    # Create concat list file
    concat_list = FFMPEG_WORK_DIR / f"concat_{uuid.uuid4().hex[:8]}.txt"
    with open(concat_list, "w") as f:
        for p in input_paths:
            # Escape single quotes in filenames for FFmpeg
            safe_path = str(Path(p).resolve()).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    try:
        if media_type == "video":
            _run_ffmpeg([
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(out),
            ], "Concatenate videos")
        elif media_type == "audio":
            _run_ffmpeg([
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:a", "libmp3lame", "-q:a", "2",
                str(out),
            ], "Concatenate audio")
        else:
            raise ValueError(f"Cannot concatenate {media_type} files")
    finally:
        concat_list.unlink(missing_ok=True)

    return out


def change_aspect_ratio(
    input_path: str | Path,
    width: int,
    height: int,
    pad_color: str = "black",
    output_path: str | Path | None = None,
) -> Path:
    """
    Change the aspect ratio / resolution of a video or image.

    Adds padding (letterbox/pillarbox) to maintain the original content
    without stretching. For audio, this is a no-op (copies the file).

    Common ratios: 16:9 (1920x1080), 9:16 (1080x1920), 1:1 (1080x1080), 4:3 (1440x1080)
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type == "audio":
        out = Path(output_path) if output_path else _make_output_path(input_path, "ratio", ext=input_path.suffix)
        shutil.copy2(input_path, out)
        return out

    out = Path(output_path) if output_path else _make_output_path(input_path, "ratio")

    if media_type == "video":
        # scale + pad to target aspect ratio
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad_color}"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(out),
        ], f"Change aspect ratio to {width}x{height}")
    elif media_type == "image":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad_color}"
            ),
            str(out),
        ], f"Resize image to {width}x{height}")

    return out


def resize(
    input_path: str | Path,
    width: int | None = None,
    height: int | None = None,
    scale_percent: float | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """
    Resize video or image.

    Provide width and/or height (the other is calculated to maintain aspect ratio),
    or scale_percent (e.g., 50 for half size).
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type == "audio":
        out = Path(output_path) if output_path else _make_output_path(input_path, "resize", ext=input_path.suffix)
        shutil.copy2(input_path, out)
        return out

    out = Path(output_path) if output_path else _make_output_path(input_path, "resize")

    # Build scale filter
    if scale_percent:
        scale_filter = f"scale=iw*{scale_percent/100}:ih*{scale_percent/100}"
    elif width and height:
        scale_filter = f"scale={width}:{height}"
    elif width:
        scale_filter = f"scale={width}:-2"
    elif height:
        scale_filter = f"scale=-2:{height}"
    else:
        raise ValueError("Provide width, height, or scale_percent")

    if media_type == "video":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", scale_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(out),
        ], "Resize video")
    elif media_type == "image":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", scale_filter,
            str(out),
        ], "Resize image")

    return out


def compress(
    input_path: str | Path,
    quality: str = "medium",
    target_bitrate: str | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """
    Compress a media file.

    Quality presets:
    - low: smallest file, visible quality loss (CRF 32)
    - medium: balanced (CRF 26)
    - high: good quality, moderate size (CRF 20)
    - very_high: near-lossless (CRF 15)

    For audio: adjusts bitrate.
    For images: adjusts quality (q:v).
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type == "image":
        # Use JPEG quality for images
        quality_map = {"low": "35", "medium": "25", "high": "15", "very_high": "5"}
        q = quality_map.get(quality, "25")
        ext = Path(input_path).suffix.lower()
        # Ensure output is jpg/png for quality adjustment
        out_ext = ".jpg" if ext in {".jpg", ".jpeg"} else ext
        out = Path(output_path) if output_path else _make_output_path(input_path, "compressed", ext=out_ext)
        _run_ffmpeg([
            "-i", str(input_path),
            "-q:v", q,
            str(out),
        ], f"Compress image (quality={quality})")
        return out

    out = Path(output_path) if output_path else _make_output_path(input_path, "compressed")

    if media_type == "video":
        crf_map = {"low": "32", "medium": "26", "high": "20", "very_high": "15"}
        crf = crf_map.get(quality, "26")

        cmd = ["-i", str(input_path)]
        if target_bitrate:
            cmd += ["-b:v", target_bitrate, "-maxrate", target_bitrate, "-bufsize", target_bitrate]
        else:
            cmd += ["-crf", crf]
        cmd += [
            "-preset", "fast",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            str(out),
        ]
        _run_ffmpeg(cmd, f"Compress video (quality={quality})")

    elif media_type == "audio":
        bitrate_map = {"low": "64k", "medium": "128k", "high": "192k", "very_high": "320k"}
        br = target_bitrate or bitrate_map.get(quality, "128k")
        _run_ffmpeg([
            "-i", str(input_path),
            "-c:a", "libmp3lame", "-b:a", br,
            str(out),
        ], f"Compress audio (bitrate={br})")

    return out


def extract_audio(
    input_path: str | Path,
    codec: str = "mp3",
    bitrate: str = "192k",
    output_path: str | Path | None = None,
) -> Path:
    """
    Extract audio from a video file, or convert audio to a different codec.

    Supported codecs: mp3, aac, opus, flac, wav, m4a
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    codec_map = {
        "mp3": (["-c:a", "libmp3lame", "-b:a", bitrate], ".mp3"),
        "aac": (["-c:a", "aac", "-b:a", bitrate], ".m4a"),
        "opus": (["-c:a", "libopus", "-b:a", bitrate], ".opus"),
        "flac": (["-c:a", "flac"], ".flac"),
        "wav": (["-c:a", "pcm_s16le"], ".wav"),
        "m4a": (["-c:a", "aac", "-b:a", bitrate], ".m4a"),
    }

    if codec not in codec_map:
        raise ValueError(f"Unsupported codec: {codec}. Use one of: {', '.join(codec_map.keys())}")

    codec_args, ext = codec_map[codec]
    out = Path(output_path) if output_path else _make_output_path(input_path, "audio", ext=ext)

    if media_type == "image":
        raise ValueError("Cannot extract audio from an image file")

    # For audio input, convert. For video input, extract.
    _run_ffmpeg([
        "-i", str(input_path),
        "-vn",  # no video
        *codec_args,
        str(out),
    ], f"Extract audio ({codec})")

    return out


def add_audio(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path | None = None,
    replace: bool = True,
) -> Path:
    """
    Merge audio into a video file.

    If replace=True, replaces the video's original audio.
    If replace=False, mixes the audio tracks together.
    """
    video_path = Path(video_path)
    audio_path = Path(audio_path)
    out = Path(output_path) if output_path else _make_output_path(video_path, "merged_audio")

    if replace:
        _run_ffmpeg([
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            "-movflags", "+faststart",
            str(out),
        ], "Replace audio in video")
    else:
        _run_ffmpeg([
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(out),
        ], "Mix audio into video")

    return out


def rotate(
    input_path: str | Path,
    angle: int = 90,
    output_path: str | Path | None = None,
) -> Path:
    """
    Rotate a video or image by the specified angle.

    Supported angles: 90, 180, 270 (clockwise). Also supports arbitrary degrees.
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type == "audio":
        out = Path(output_path) if output_path else _make_output_path(input_path, "rotated", ext=input_path.suffix)
        shutil.copy2(input_path, out)
        return out

    out = Path(output_path) if output_path else _make_output_path(input_path, "rotated")

    # Build transpose filter
    angle_map = {
        90: "transpose=1",       # 90 clockwise
        180: "transpose=1,transpose=1",  # 180
        270: "transpose=2",      # 90 counter-clockwise
    }

    if angle in angle_map:
        vf = angle_map[angle]
    else:
        # Arbitrary angle rotation
        vf = f"rotate={angle}*PI/180:fillcolor=black"

    if media_type == "video":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(out),
        ], f"Rotate {angle}°")
    elif media_type == "image":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            str(out),
        ], f"Rotate image {angle}°")

    return out


def flip(
    input_path: str | Path,
    direction: str = "horizontal",
    output_path: str | Path | None = None,
) -> Path:
    """
    Flip/mirror a video or image.

    direction: 'horizontal' (left-right) or 'vertical' (top-bottom)
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type == "audio":
        out = Path(output_path) if output_path else _make_output_path(input_path, "flipped", ext=input_path.suffix)
        shutil.copy2(input_path, out)
        return out

    out = Path(output_path) if output_path else _make_output_path(input_path, "flipped")
    vf = "hflip" if direction == "horizontal" else "vflip"

    if media_type == "video":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(out),
        ], f"Flip {direction}")
    elif media_type == "image":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            str(out),
        ], f"Flip image {direction}")

    return out


def change_speed(
    input_path: str | Path,
    speed: float = 1.0,
    output_path: str | Path | None = None,
) -> Path:
    """
    Change playback speed of video/audio.

    speed: multiplier (0.5 = half speed, 2.0 = double speed)
    Clamped between 0.25x and 4.0x for safety.
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type == "image":
        out = Path(output_path) if output_path else _make_output_path(input_path, "speed", ext=input_path.suffix)
        shutil.copy2(input_path, out)
        return out

    speed = max(0.25, min(4.0, speed))
    out = Path(output_path) if output_path else _make_output_path(input_path, f"speed{speed}x")

    atempo_filters = []
    remaining = speed
    # FFmpeg atempo only supports 0.5-100.0 per instance
    while remaining > 2.0:
        atempo_filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        atempo_filters.append("atempo=0.5")
        remaining /= 0.5
    atempo_filters.append(f"atempo={remaining}")
    atempo = ",".join(atempo_filters)

    if media_type == "video":
        _run_ffmpeg([
            "-i", str(input_path),
            "-filter_complex",
            f"[0:v]setpts={1/speed}*PTS[v];[0:a]{atempo}[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out),
        ], f"Change speed to {speed}x")
    elif media_type == "audio":
        _run_ffmpeg([
            "-i", str(input_path),
            "-filter:a", atempo,
            str(out),
        ], f"Change audio speed to {speed}x")

    return out


def generate_thumbnail(
    input_path: str | Path,
    timestamp: float = 1.0,
    output_path: str | Path | None = None,
) -> Path:
    """
    Extract a single thumbnail frame from a video at the given timestamp.
    Returns a JPEG image.
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type != "video":
        raise ValueError("Thumbnails can only be extracted from video files")

    out = Path(output_path) if output_path else _make_output_path(input_path, "thumb", ext=".jpg")

    _run_ffmpeg([
        "-i", str(input_path),
        "-ss", str(timestamp),
        "-vframes", "1",
        "-q:v", "2",
        str(out),
    ], f"Generate thumbnail at {timestamp}s")

    return out


def watermark(
    input_path: str | Path,
    watermark_path: str | Path,
    position: str = "bottom_right",
    opacity: float = 0.7,
    scale: float = 0.15,
    output_path: str | Path | None = None,
) -> Path:
    """
    Add an image watermark to a video.

    position: top_left, top_right, bottom_left, bottom_right, center
    opacity: 0.0-1.0
    scale: watermark size as fraction of video width (0.0-1.0)
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type != "video":
        raise ValueError("Watermark can only be applied to video files")

    out = Path(output_path) if output_path else _make_output_path(input_path, "watermarked")

    pos_map = {
        "top_left": "20:20",
        "top_right": "main_w-overlay_w-20:20",
        "bottom_left": "20:main_h-overlay_h-20",
        "bottom_right": "main_w-overlay_w-20:main_h-overlay_h-20",
        "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
    }
    overlay_pos = pos_map.get(position, pos_map["bottom_right"])

    _run_ffmpeg([
        "-i", str(input_path),
        "-i", str(watermark_path),
        "-filter_complex",
        (
            f"[1:v]format=rgba,scale=iw*{scale}:-1,"
            f"colorchannelmixer=aa={opacity}[wm];"
            f"[0:v][wm]overlay={overlay_pos}"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out),
    ], "Add watermark")

    return out


def extract_clip(
    input_path: str | Path,
    start: float,
    duration: float,
    output_path: str | Path | None = None,
) -> Path:
    """
    Extract a clip of specified duration starting from a timestamp.
    More efficient than trim() for known durations.
    """
    return trim(input_path, start, start + duration, output_path)


def get_duration(file_path: str | Path) -> float:
    """Get the duration of a media file in seconds."""
    info = probe(file_path)
    return info.get("duration", 0.0)


def get_media_info(file_path: str | Path) -> dict[str, Any]:
    """Get comprehensive media information."""
    return probe(file_path)


def convert_format(
    input_path: str | Path,
    output_format: str,
    output_path: str | Path | None = None,
) -> Path:
    """
    Convert a media file to a different format.

    Common conversions: mp4→webm, mp3→wav, png→jpg, etc.
    """
    input_path = Path(input_path)

    format_ext_map = {
        "mp4": ".mp4", "webm": ".webm", "mkv": ".mkv", "avi": ".avi", "mov": ".mov",
        "mp3": ".mp3", "wav": ".wav", "flac": ".flac", "aac": ".m4a", "ogg": ".ogg", "opus": ".opus",
        "jpg": ".jpg", "jpeg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp",
    }

    ext = format_ext_map.get(output_format.lower())
    if not ext:
        raise ValueError(f"Unsupported output format: {output_format}")

    out = Path(output_path) if output_path else _make_output_path(input_path, "converted", ext=ext)
    media_type = _detect_media_type(input_path)

    cmd = ["-i", str(input_path)]

    if media_type == "video":
        cmd += [
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
        ]
    elif media_type == "audio":
        cmd += ["-c:a", "libmp3lame", "-q:a", "2"]
    # Images: FFmpeg auto-detects from extension

    cmd.append(str(out))
    _run_ffmpeg(cmd, f"Convert to {output_format}")

    return out


def crop(
    input_path: str | Path,
    x: int,
    y: int,
    width: int,
    height: int,
    output_path: str | Path | None = None,
) -> Path:
    """
    Crop a video or image to a specific region.

    x, y: top-left corner of the crop region
    width, height: size of the crop region
    """
    input_path = Path(input_path)
    media_type = _detect_media_type(input_path)

    if media_type == "audio":
        raise ValueError("Cannot crop audio files")

    out = Path(output_path) if output_path else _make_output_path(input_path, "cropped")
    vf = f"crop={width}:{height}:{x}:{y}"

    if media_type == "video":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(out),
        ], f"Crop to {width}x{height}")
    elif media_type == "image":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            str(out),
        ], f"Crop image to {width}x{height}")

    return out


def add_subtitles(
    video_path: str | Path,
    subtitle_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    """
    Burn subtitles into a video (hardcoded subtitles).

    Supports .srt, .ass, .vtt subtitle formats.
    """
    video_path = Path(video_path)
    subtitle_path = Path(subtitle_path)
    out = Path(output_path) if output_path else _make_output_path(video_path, "subtitled")

    _run_ffmpeg([
        "-i", str(video_path),
        "-vf", f"subtitles={str(subtitle_path)}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out),
    ], "Add subtitles")

    return out


# ── Cleanup ───────────────────────────────────────────────────────────────────

def cleanup_work_dir(max_age_seconds: int = 900) -> int:
    """
    Remove all files in the FFmpeg work directory older than max_age_seconds.
    Returns the number of files removed.
    """
    import time
    now = time.time()
    removed = 0
    if not FFMPEG_WORK_DIR.exists():
        return 0
    for f in FFMPEG_WORK_DIR.iterdir():
        if f.is_file():
            if (now - f.stat().st_mtime) > max_age_seconds:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


# ── Capability Check ──────────────────────────────────────────────────────────

def get_available_features() -> dict[str, Any]:
    """Check what FFmpeg features are available on this system."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    ffmpeg_version = ""
    encoders = []

    if ffmpeg:
        try:
            result = subprocess.run(
                [ffmpeg, "-version"],
                capture_output=True, text=True, timeout=5
            )
            first_line = result.stdout.split("\n")[0] if result.stdout else ""
            ffmpeg_version = first_line
        except Exception:
            pass

        # Check for key encoders
        try:
            result = subprocess.run(
                [ffmpeg, "-encoders"],
                capture_output=True, text=True, timeout=5
            )
            for encoder in ["libx264", "libx265", "libmp3lame", "aac", "libopus", "libvpx"]:
                if encoder in result.stdout:
                    encoders.append(encoder)
        except Exception:
            pass

    return {
        "ffmpeg_available": ffmpeg is not None,
        "ffprobe_available": ffprobe is not None,
        "ffmpeg_path": ffmpeg,
        "ffprobe_path": ffprobe,
        "ffmpeg_version": ffmpeg_version,
        "available_encoders": encoders,
        "features": {
            "trim": ffmpeg is not None,
            "concatenate": ffmpeg is not None,
            "resize": ffmpeg is not None,
            "change_aspect_ratio": ffmpeg is not None,
            "compress": ffmpeg is not None,
            "extract_audio": ffmpeg is not None,
            "add_audio": ffmpeg is not None,
            "rotate": ffmpeg is not None,
            "flip": ffmpeg is not None,
            "change_speed": ffmpeg is not None,
            "watermark": ffmpeg is not None,
            "crop": ffmpeg is not None,
            "generate_thumbnail": ffmpeg is not None,
            "add_subtitles": ffmpeg is not None,
            "convert_format": ffmpeg is not None,
            "probe": ffprobe is not None,
        },
    }
