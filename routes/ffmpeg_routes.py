"""
MediaForge — FFmpeg Processing Routes

FastAPI router exposing all FFmpeg media processing operations as API endpoints.
Each endpoint accepts file uploads and returns processed files.

File cleanup: All processed files are tracked and auto-deleted after 15 minutes.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

import ffmpeg_ops

router = APIRouter(prefix="/ffmpeg", tags=["FFmpeg Processing"])

# ── Upload Directory ──────────────────────────────────────────────────────────

UPLOAD_DIR = ffmpeg_ops.FFMPEG_WORK_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# File tracker (shared pattern with main.py, but separate tracker for FFmpeg files)
TRACKER_FILE = ffmpeg_ops.FFMPEG_WORK_DIR / ".tracker.json"
MAX_FILE_AGE = 15 * 60  # 15 minutes


def _load_tracker() -> dict:
    if TRACKER_FILE.exists():
        try:
            import json
            return json.loads(TRACKER_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_tracker(data: dict):
    try:
        import json
        TRACKER_FILE.write_text(json.dumps(data))
    except OSError:
        pass


def _track_file(file_path: Path):
    tracker = _load_tracker()
    tracker[str(file_path)] = {
        "created_at": time.time(),
        "filename": file_path.name,
    }
    _save_tracker(tracker)


def cleanup_ffmpeg_files():
    """Remove tracked FFmpeg files older than MAX_FILE_AGE."""
    import json
    now = time.time()
    tracker = _load_tracker()
    to_remove = []

    for fpath_str, meta in tracker.items():
        created = meta.get("created_at", 0)
        if (now - created) > MAX_FILE_AGE:
            to_remove.append(fpath_str)

    # Sweep work dir and uploads dir
    for directory in [ffmpeg_ops.FFMPEG_WORK_DIR, UPLOAD_DIR]:
        if directory.exists():
            for f in directory.iterdir():
                if f.is_file() and f.name != ".tracker.json":
                    if (now - f.stat().st_mtime) > MAX_FILE_AGE:
                        to_remove.append(str(f))

    removed = 0
    for fpath_str in set(to_remove):
        p = Path(fpath_str)
        if p.exists():
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        tracker.pop(fpath_str, None)

    if removed > 0:
        _save_tracker(tracker)

    return removed


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _save_upload(upload: UploadFile) -> Path:
    """Save an uploaded file to disk and return its path."""
    ext = Path(upload.filename or "file").suffix or ".bin"
    unique_name = f"{uuid.uuid4().hex[:10]}{ext}"
    file_path = UPLOAD_DIR / unique_name

    content = await upload.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > 500 * 1024 * 1024:  # 500MB limit
        raise HTTPException(status_code=413, detail="File too large (max 500MB)")

    file_path.write_bytes(content)
    _track_file(file_path)
    return file_path


def _serve_result(file_path: Path, suffix: str = "") -> FileResponse:
    """Serve a processed file as a download."""
    if not file_path.exists():
        raise HTTPException(status_code=500, detail="Processing produced no output file")

    file_size = file_path.stat().st_size
    if file_size == 0:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Output file is empty")

    _track_file(file_path)

    ext = file_path.suffix.lower()
    content_type_map = {
        ".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo", ".mov": "video/quicktime",
        ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".opus": "audio/opus",
        ".ogg": "audio/ogg", ".wav": "audio/wav", ".flac": "audio/flac",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp",
    }

    download_name = file_path.name
    if suffix:
        stem = file_path.stem
        download_name = f"{stem}_{suffix}{ext}"

    return FileResponse(
        path=str(file_path),
        media_type=content_type_map.get(ext, "application/octet-stream"),
        filename=download_name,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _handle_ffmpeg_error(e: Exception) -> HTTPException:
    """Convert FFmpeg errors to HTTP exceptions with helpful messages."""
    msg = str(e)
    if "FFmpeg is not installed" in msg:
        return HTTPException(
            status_code=501,
            detail="FFmpeg is not installed on this server. Media processing features require FFmpeg. "
                   "Please install FFmpeg and restart the server."
        )
    return HTTPException(status_code=500, detail=f"Processing failed: {msg}")


# ── Feature Check ─────────────────────────────────────────────────────────────


@router.get("/features")
async def get_features():
    """Check which FFmpeg features are available on this system."""
    try:
        return ffmpeg_ops.get_available_features()
    except Exception as e:
        return {"ffmpeg_available": False, "error": str(e)}


# ── Probe ─────────────────────────────────────────────────────────────────────


@router.post("/probe")
async def probe_file(file: UploadFile = File(...)):
    """
    Probe a media file and return comprehensive metadata.

    Returns codec info, duration, resolution, bitrate, streams, etc.
    """
    try:
        file_path = await _save_upload(file)
        info = ffmpeg_ops.probe(file_path)
        return {"success": True, **info}
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Trim ──────────────────────────────────────────────────────────────────────


@router.post("/trim")
async def trim_media(
    file: UploadFile = File(...),
    start: float = Form(..., description="Start time in seconds"),
    end: float = Form(..., description="End time in seconds"),
):
    """
    Trim/cut a media file from start to end time.

    Works with video, audio. Returns the trimmed file as a download.
    """
    if start < 0:
        raise HTTPException(status_code=400, detail="Start time must be >= 0")
    if end <= start:
        raise HTTPException(status_code=400, detail="End time must be greater than start time")

    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.trim(file_path, start, end)
        return _serve_result(out, "trimmed")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Concatenate ───────────────────────────────────────────────────────────────


@router.post("/concatenate")
async def concatenate_media(files: list[UploadFile] = File(..., min_length=2, max_length=20)):
    """
    Join multiple media files of the same type into one.

    Upload 2-20 files. All must be the same media type (all video or all audio).
    """
    try:
        paths = []
        for f in files:
            p = await _save_upload(f)
            paths.append(p)

        out = ffmpeg_ops.concatenate(paths)
        return _serve_result(out, "joined")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Resize ────────────────────────────────────────────────────────────────────


@router.post("/resize")
async def resize_media(
    file: UploadFile = File(...),
    width: int | None = Form(default=None, description="Target width"),
    height: int | None = Form(default=None, description="Target height"),
    scale_percent: float | None = Form(default=None, description="Scale by percentage (e.g., 50 = half)"),
):
    """
    Resize a video or image.

    Provide width and/or height (other dimension auto-calculated to maintain aspect ratio),
    or scale_percent to scale by a percentage.
    """
    if not width and not height and not scale_percent:
        raise HTTPException(status_code=400, detail="Provide width, height, or scale_percent")

    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.resize(file_path, width=width, height=height, scale_percent=scale_percent)
        return _serve_result(out, "resized")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Aspect Ratio ──────────────────────────────────────────────────────────────


@router.post("/aspect-ratio")
async def change_aspect_ratio(
    file: UploadFile = File(...),
    width: int = Form(..., description="Target width (e.g., 1920)"),
    height: int = Form(..., description="Target height (e.g., 1080)"),
    pad_color: str = Form(default="black", description="Padding color"),
):
    """
    Change the aspect ratio of a video or image.

    Adds padding (letterbox/pillarbox) to fit the target dimensions
    without stretching the content.

    Common ratios: 16:9 (1920x1080), 9:16 (1080x1920), 1:1 (1080x1080), 4:3 (1440x1080)
    """
    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.change_aspect_ratio(file_path, width, height, pad_color)
        return _serve_result(out, "aspect_ratio")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Compress ──────────────────────────────────────────────────────────────────


@router.post("/compress")
async def compress_media(
    file: UploadFile = File(...),
    quality: str = Form(default="medium", description="Quality: low, medium, high, very_high"),
    target_bitrate: str | None = Form(default=None, description="Target bitrate (e.g., 1M, 500k)"),
):
    """
    Compress a media file to reduce its size.

    Quality presets:
    - low: smallest file, visible quality loss
    - medium: balanced (default)
    - high: good quality, moderate size
    - very_high: near-lossless

    For video: uses CRF encoding. For audio: adjusts bitrate. For images: JPEG quality.
    """
    valid_qualities = {"low", "medium", "high", "very_high"}
    if quality not in valid_qualities:
        raise HTTPException(status_code=400, detail=f"Invalid quality. Use: {', '.join(valid_qualities)}")

    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.compress(file_path, quality=quality, target_bitrate=target_bitrate)
        return _serve_result(out, f"compressed_{quality}")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Extract Audio ─────────────────────────────────────────────────────────────


@router.post("/extract-audio")
async def extract_audio_from_media(
    file: UploadFile = File(...),
    codec: str = Form(default="mp3", description="Output codec: mp3, aac, opus, flac, wav, m4a"),
    bitrate: str = Form(default="192k", description="Audio bitrate"),
):
    """
    Extract audio from a video, or convert audio to a different codec.

    Supported codecs: mp3, aac, opus, flac, wav, m4a
    """
    valid_codecs = {"mp3", "aac", "opus", "flac", "wav", "m4a"}
    if codec not in valid_codecs:
        raise HTTPException(status_code=400, detail=f"Invalid codec. Use: {', '.join(valid_codecs)}")

    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.extract_audio(file_path, codec=codec, bitrate=bitrate)
        return _serve_result(out, f"audio_{codec}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Add Audio to Video ────────────────────────────────────────────────────────


@router.post("/add-audio")
async def add_audio_to_video(
    video: UploadFile = File(..., description="Video file"),
    audio: UploadFile = File(..., description="Audio file to add"),
    replace: bool = Form(default=True, description="Replace original audio (True) or mix (False)"),
):
    """
    Merge an audio track into a video file.

    If replace=True: replaces the video's original audio.
    If replace=False: mixes the audio tracks together.
    """
    try:
        video_path = await _save_upload(video)
        audio_path = await _save_upload(audio)
        out = ffmpeg_ops.add_audio(video_path, audio_path, replace=replace)
        return _serve_result(out, "audio_merged")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Rotate ────────────────────────────────────────────────────────────────────


@router.post("/rotate")
async def rotate_media(
    file: UploadFile = File(...),
    angle: int = Form(default=90, description="Rotation angle: 90, 180, 270"),
):
    """
    Rotate a video or image by the specified angle (clockwise).

    Supported angles: 90, 180, 270 degrees.
    """
    valid_angles = {90, 180, 270}
    if angle not in valid_angles:
        raise HTTPException(status_code=400, detail=f"Invalid angle. Use: {', '.join(str(a) for a in valid_angles)}")

    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.rotate(file_path, angle=angle)
        return _serve_result(out, f"rotated_{angle}")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Flip ──────────────────────────────────────────────────────────────────────


@router.post("/flip")
async def flip_media(
    file: UploadFile = File(...),
    direction: str = Form(default="horizontal", description="Flip direction: horizontal or vertical"),
):
    """
    Flip/mirror a video or image horizontally or vertically.
    """
    valid_directions = {"horizontal", "vertical"}
    if direction not in valid_directions:
        raise HTTPException(status_code=400, detail=f"Invalid direction. Use: {', '.join(valid_directions)}")

    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.flip(file_path, direction=direction)
        return _serve_result(out, f"flipped_{direction}")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Change Speed ──────────────────────────────────────────────────────────────


@router.post("/speed")
async def change_speed_media(
    file: UploadFile = File(...),
    speed: float = Form(default=1.0, description="Speed multiplier (0.25 to 4.0)"),
):
    """
    Change the playback speed of video/audio.

    speed: multiplier (0.5 = half speed, 2.0 = double speed).
    Clamped between 0.25x and 4.0x.
    """
    if speed < 0.25 or speed > 4.0:
        raise HTTPException(status_code=400, detail="Speed must be between 0.25 and 4.0")

    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.change_speed(file_path, speed=speed)
        return _serve_result(out, f"speed_{speed}x")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Crop ──────────────────────────────────────────────────────────────────────


@router.post("/crop")
async def crop_media(
    file: UploadFile = File(...),
    x: int = Form(..., description="Top-left X coordinate"),
    y: int = Form(..., description="Top-left Y coordinate"),
    width: int = Form(..., description="Crop width"),
    height: int = Form(..., description="Crop height"),
):
    """
    Crop a video or image to a specific region.

    x, y: top-left corner of the crop region.
    width, height: size of the crop region.
    """
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=400, detail="Width and height must be positive")

    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.crop(file_path, x=x, y=y, width=width, height=height)
        return _serve_result(out, "cropped")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Convert Format ────────────────────────────────────────────────────────────


@router.post("/convert")
async def convert_format_media(
    file: UploadFile = File(...),
    output_format: str = Form(..., description="Target format: mp4, webm, mp3, wav, jpg, png, etc."),
):
    """
    Convert a media file to a different format.

    Common conversions: mp4→webm, mp3→wav, png→jpg, etc.
    """
    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.convert_format(file_path, output_format)
        return _serve_result(out, f"converted_{output_format}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Generate Thumbnail ────────────────────────────────────────────────────────


@router.post("/thumbnail")
async def generate_thumbnail_media(
    file: UploadFile = File(...),
    timestamp: float = Form(default=1.0, description="Timestamp in seconds for the thumbnail"),
):
    """
    Extract a single thumbnail frame from a video at the specified timestamp.

    Returns a JPEG image.
    """
    if timestamp < 0:
        raise HTTPException(status_code=400, detail="Timestamp must be >= 0")

    try:
        file_path = await _save_upload(file)
        out = ffmpeg_ops.generate_thumbnail(file_path, timestamp=timestamp)
        return _serve_result(out, "thumbnail")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Watermark ─────────────────────────────────────────────────────────────────


@router.post("/watermark")
async def add_watermark_media(
    video: UploadFile = File(..., description="Video file"),
    watermark: UploadFile = File(..., description="Watermark image (PNG with transparency recommended)"),
    position: str = Form(default="bottom_right", description="Position: top_left, top_right, bottom_left, bottom_right, center"),
    opacity: float = Form(default=0.7, description="Watermark opacity (0.0-1.0)"),
    scale: float = Form(default=0.15, description="Watermark size as fraction of video width"),
):
    """
    Add an image watermark to a video.

    Supports PNG images with transparency. Position can be any corner or center.
    """
    valid_positions = {"top_left", "top_right", "bottom_left", "bottom_right", "center"}
    if position not in valid_positions:
        raise HTTPException(status_code=400, detail=f"Invalid position. Use: {', '.join(valid_positions)}")
    if opacity < 0 or opacity > 1:
        raise HTTPException(status_code=400, detail="Opacity must be between 0.0 and 1.0")

    try:
        video_path = await _save_upload(video)
        watermark_path = await _save_upload(watermark)
        out = ffmpeg_ops.watermark(video_path, watermark_path, position=position, opacity=opacity, scale=scale)
        return _serve_result(out, "watermarked")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Burn Subtitles ────────────────────────────────────────────────────────────


@router.post("/subtitles")
async def burn_subtitles(
    video: UploadFile = File(..., description="Video file"),
    subtitle: UploadFile = File(..., description="Subtitle file (.srt, .ass, .vtt)"),
):
    """
    Burn (hardcode) subtitles into a video.

    Supports .srt, .ass, and .vtt subtitle formats.
    """
    sub_ext = Path(subtitle.filename or "").suffix.lower()
    if sub_ext not in {".srt", ".ass", ".vtt"}:
        raise HTTPException(status_code=400, detail="Subtitle must be .srt, .ass, or .vtt format")

    try:
        video_path = await _save_upload(video)
        subtitle_path = await _save_upload(subtitle)
        out = ffmpeg_ops.add_subtitles(video_path, subtitle_path)
        return _serve_result(out, "subtitled")
    except RuntimeError as e:
        raise _handle_ffmpeg_error(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Cleanup Endpoint ──────────────────────────────────────────────────────────


@router.post("/cleanup")
async def trigger_cleanup():
    """Manually trigger cleanup of old FFmpeg files."""
    removed = cleanup_ffmpeg_files()
    return {"success": True, "files_removed": removed}
