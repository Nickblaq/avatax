"""Core extraction logic wrapping yt-dlp's Python API (v2026.08.19+)."""

from __future__ import annotations

import re
from typing import Any

import yt_dlp
from yt_dlp import YoutubeDL

from models import (
    BatchExtractRequest,
    BatchExtractResponse,
    DownloadRequest,
    ExtractRequest,
    ExtractResponse,
    FormatInfo,
    MediaInfo,
    MediaType,
    PlaylistItem,
    PlaylistRequest,
    PlaylistResponse,
    QualityPreset,
)

# ── Platform Detection ───────────────────────────────────────────────────────

PLATFORM_PATTERNS: list[tuple[str, str, str]] = [
    (r"(youtube\.com|youtu\.be)", "YouTube", "youtube"),
    (r"(twitter\.com|x\.com)", "Twitter/X", "twitter"),
    (r"(instagram\.com)", "Instagram", "instagram"),
    (r"(tiktok\.com)", "TikTok", "tiktok"),
    (r"(facebook\.com|fb\.watch)", "Facebook", "facebook"),
    (r"(vimeo\.com)", "Vimeo", "vimeo"),
    (r"(twitch\.tv)", "Twitch", "twitch"),
    (r"(soundcloud\.com)", "SoundCloud", "soundcloud"),
    (r"(reddit\.com|redd\.it)", "Reddit", "reddit"),
    (r"(dailymotion\.com)", "Dailymotion", "dailymotion"),
    (r"(bilibili\.com)", "Bilibili", "bilibili"),
    (r"(tumblr\.com)", "Tumblr", "tumblr"),
    (r"(twitch\.tv)", "Twitch", "twitch"),
    (r"(pornhub\.com)", "Pornhub", "pornhub"),
    (r"(xvideos\.com)", "XVideos", "xvideos"),
    (r"(xhamster\.com)", "xHamster", "xhamster"),
    (r"(redgifs\.com)", "RedGIFs", "redgifs"),
    (r"(streamable\.com)", "Streamable", "streamable"),
    (r"(twitch\.tv)", "Twitch", "twitch"),
    (r"(vimeo\.com)", "Vimeo", "vimeo"),
    (r"(rutube\.ru)", "Rutube", "rutube"),
    (r"(ok\.ru)", "OK.ru", "okru"),
    (r"(vk\.com|vkvideo\.ru)", "VK", "vk"),
    (r"(peertube)", "PeerTube", "peertube"),
    (r"(loom\.com)", "Loom", "loom"),
    (r"(streamja\.com)", "Streamja", "streamja"),
    (r"(mixer\.com|beam\.pro)", "Mixer", "mixer"),
    (r"(nicovideo\.jp)", "Niconico", "niconico"),
    (r"(bitchute\.com)", "BitChute", "bitchute"),
    (r"(rumble\.com)", "Rumble", "rumble"),
    (r"(odysee\.com|lbry\.tv)", "Odysee/LBRY", "odysee"),
]

SUPPORTED_PLATFORMS: list[str] = sorted({p[2] for p in PLATFORM_PATTERNS})


def detect_platform(url: str) -> tuple[str, str]:
    """Detect the platform from a URL. Returns (display_name, key)."""
    for pattern, name, key in PLATFORM_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return name, key
    return "Unknown", "generic"


# ── Quality Mapping ──────────────────────────────────────────────────────────

QUALITY_FORMATS: dict[QualityPreset, str] = {
    QualityPreset.BEST: "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
    QualityPreset.GOOD: "best[height<=720][ext=mp4]/best[height<=720]/best",
    QualityPreset.WORST: "worst[ext=mp4]/worst",
    QualityPreset.AUDIO_ONLY: "bestaudio[ext=m4a]/bestaudio/best",
    QualityPreset.CUSTOM: "bestvideo+bestaudio/best",
}


def _detect_media_type(info: dict[str, Any]) -> str:
    """Detect whether the content is video, audio, image, or gallery."""
    if info.get("_type") == "multi_image":
        return "image"
    ext = (info.get("ext") or "").lower()
    vcodec = (info.get("vcodec") or "none").lower()
    acodec = (info.get("acodec") or "none").lower()
    image_exts = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "avif"}
    if ext in image_exts:
        return "image"
    if vcodec == "none" and acodec != "none":
        return "audio"
    return "video"


def _format_duration(seconds: float | None) -> str:
    """Convert seconds to human-readable duration string."""
    if not seconds:
        return ""
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _build_ydl_opts(
    request: ExtractRequest | DownloadRequest,
    *,
    download: bool = False,
    extract_flat: bool = False,
) -> dict[str, Any]:
    """Build yt-dlp options dict from an ExtractRequest."""
    fmt = QUALITY_FORMATS.get(request.quality, QUALITY_FORMATS[QualityPreset.BEST])
    if request.quality == QualityPreset.CUSTOM and request.format_id:
        fmt = request.format_id

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "format": fmt,
        "extract_flat": extract_flat,
        "ignoreerrors": "only_download",
        "no_color": True,
        "geo_bypass": True,
        "socket_timeout": 30,
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "web_embedded", "mweb"],
            },
        },
    }

    if download:
        opts["skip_download"] = False
        opts["outtmpl"] = "/tmp/yt-dlp/%(title).80s-%(id)s.%(ext)s"
    else:
        opts["skip_download"] = True

    # Platform-specific tweaks
    _, platform_key = detect_platform(request.url) if hasattr(request, "url") else ("", "")
    if platform_key == "twitter":
        opts["extractor_args"]["twitter"] = {"api_hostname": "api.twitter.com"}
    elif platform_key == "instagram":
        opts["extractor_args"]["instagram"] = {"api_hostname": "i.instagram.com"}
    elif platform_key == "tiktok":
        opts["extractor_args"]["tiktok"] = {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}

    if request.cookies:
        opts["http_headers"] = {
            "Cookie": request.cookies,
        }

    return opts


def _format_to_model(f: dict[str, Any]) -> FormatInfo:
    """Convert a yt-dlp format dict to our FormatInfo model."""
    vcodec = (f.get("vcodec") or "none").lower()
    acodec = (f.get("acodec") or "none").lower()
    return FormatInfo(
        format_id=str(f.get("format_id", "")),
        ext=str(f.get("ext", "")),
        resolution=str(f.get("resolution", "")),
        fps=f.get("fps"),
        vcodec=f.get("vcodec") or "",
        acodec=f.get("acodec") or "",
        filesize=f.get("filesize"),
        tbr=f.get("tbr"),
        vbr=f.get("vbr"),
        abr=f.get("abr"),
        width=f.get("width"),
        height=f.get("height"),
        url=f.get("url") or "",
        format_note=str(f.get("format_note", "")),
        quality=str(f.get("quality", "")),
        has_video=vcodec != "none",
        has_audio=acodec != "none",
    )


def _info_to_media_model(info: dict[str, Any]) -> MediaInfo:
    """Convert a yt-dlp info dict to our MediaInfo model."""
    platform_name, _ = detect_platform(info.get("webpage_url") or info.get("original_url") or "")
    media_type = _detect_media_type(info)

    formats = []
    for f in (info.get("formats") or []):
        try:
            formats.append(_format_to_model(f))
        except Exception:
            continue

    # Sanitize subtitles and auto_captions
    subtitles = info.get("subtitles") or {}
    auto_captions = info.get("automatic_captions") or info.get("auto_captions") or {}

    return MediaInfo(
        id=str(info.get("id", "")),
        title=str(info.get("title", "")),
        description=str(info.get("description", "")),
        thumbnail=str(info.get("thumbnail") or (info.get("thumbnails") or [{}])[-1].get("url", "") if info.get("thumbnails") else ""),
        thumbnails=info.get("thumbnails") or [],
        duration=info.get("duration"),
        duration_string=_format_duration(info.get("duration")),
        view_count=info.get("view_count"),
        like_count=info.get("like_count"),
        upload_date=str(info.get("upload_date") or ""),
        uploader=str(info.get("uploader") or info.get("creator") or info.get("channel") or ""),
        uploader_id=str(info.get("uploader_id") or info.get("channel_id") or ""),
        channel=str(info.get("channel") or info.get("uploader") or ""),
        channel_id=info.get("channel_id"),
        channel_follower_count=info.get("channel_follower_count"),
        tags=info.get("tags") or [],
        categories=info.get("categories") or [],
        webpage_url=str(info.get("webpage_url") or info.get("url") or ""),
        original_url=str(info.get("original_url") or ""),
        extractor=str(info.get("extractor") or ""),
        extractor_key=str(info.get("extractor_key") or ""),
        platform=platform_name,
        media_type_detected=media_type,
        formats=formats,
        subtitles=subtitles,
        auto_captions=auto_captions,
        comment_count=info.get("comment_count"),
        age_limit=info.get("age_limit"),
        chapters=info.get("chapters") or [],
    )


# ── Public API Functions ─────────────────────────────────────────────────────

def extract_media(request: ExtractRequest) -> ExtractResponse:
    """Extract media information without downloading."""
    opts = _build_ydl_opts(request, download=False)
    platform_name, _ = detect_platform(request.url)

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(request.url, download=False)

    if info is None:
        return ExtractResponse(
            success=False,
            media=MediaInfo(),
            message=f"Could not extract media from: {request.url}",
        )

    info = dict(ydl.sanitize_info(info)) if isinstance(info, dict) else dict(info)
    media = _info_to_media_model(info)

    # Filter formats by media type if requested
    if request.media_type == MediaType.VIDEO:
        media.formats = [f for f in media.formats if f.has_video]
    elif request.media_type == MediaType.AUDIO:
        media.formats = [f for f in media.formats if f.has_audio and not f.has_video]
    elif request.media_type == MediaType.IMAGE:
        media.formats = [f for f in media.formats if f.ext in ("jpg", "jpeg", "png", "gif", "webp")]

    # Pick best download URL
    best_format = _select_best_format(media.formats, request.quality)
    download_url = best_format.url if best_format else None

    return ExtractResponse(
        success=True,
        media=media,
        download_url=download_url,
        message=f"Successfully extracted from {platform_name}",
    )


def extract_media_info(url: str) -> dict[str, Any]:
    """Low-level extraction returning raw sanitized info dict."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "no_color": True,
        "geo_bypass": True,
        "socket_timeout": 30,
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "web_embedded", "mweb"],
            },
        },
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        return {}
    return dict(ydl.sanitize_info(info)) if isinstance(info, dict) else {}


def extract_playlist(request: PlaylistRequest) -> PlaylistResponse:
    """Extract playlist metadata and items."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "no_color": True,
        "extract_flat": True,
        "geo_bypass": True,
        "socket_timeout": 30,
    }

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(request.url, download=False)

    if info is None:
        return PlaylistResponse(success=False, title="", description="", uploader="", playlist_count=0, items=[])

    entries = info.get("entries") or []
    items: list[PlaylistItem] = []

    for idx, entry in enumerate(entries):
        if idx >= request.limit:
            break
        if entry is None:
            continue
        entry_id = str(entry.get("id", ""))
        entry_url = entry.get("url") or entry.get("webpage_url") or f"https://youtu.be/{entry_id}"
        items.append(
            PlaylistItem(
                id=entry_id,
                title=str(entry.get("title") or ""),
                url=str(entry_url),
                duration=entry.get("duration"),
                thumbnail=str(entry.get("thumbnail") or ""),
                uploader=str(entry.get("uploader") or entry.get("channel") or ""),
                index=idx + 1,
            )
        )

    return PlaylistResponse(
        success=True,
        title=str(info.get("title") or ""),
        description=str(info.get("description") or ""),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
        playlist_count=len(items),
        items=items,
    )


def batch_extract(request: BatchExtractRequest) -> BatchExtractResponse:
    """Extract info from multiple URLs."""
    results: list[ExtractResponse] = []
    errors: list[dict[str, str]] = []

    for url in request.urls:
        try:
            req = ExtractRequest(
                url=url,
                media_type=request.media_type,
                quality=request.quality,
            )
            result = extract_media(req)
            results.append(result)
            if not result.success:
                errors.append({"url": url, "error": result.message})
        except Exception as e:
            errors.append({"url": url, "error": str(e)})

    return BatchExtractResponse(
        success=len(errors) == 0,
        results=results,
        errors=errors,
        total=len(request.urls),
        successful=sum(1 for r in results if r.success),
        failed=len(errors),
    )


def _select_best_format(formats: list[FormatInfo], quality: QualityPreset) -> FormatInfo | None:
    """Select the best format from a list."""
    if not formats:
        return None

    if quality == QualityPreset.AUDIO_ONLY:
        audio = [f for f in formats if f.has_audio and not f.has_video]
        if audio:
            return max(audio, key=lambda f: f.abr or 0)
        return max(formats, key=lambda f: f.abr or 0)

    if quality == QualityPreset.WORST:
        return min(formats, key=lambda f: f.tbr or float("inf"))

    # Best quality: prefer combined video+audio, then best video
    combined = [f for f in formats if f.has_video and f.has_audio]
    if combined:
        return max(combined, key=lambda f: (f.height or 0, f.tbr or 0))

    video = [f for f in formats if f.has_video]
    if video:
        return max(video, key=lambda f: (f.height or 0, f.tbr or 0))

    return max(formats, key=lambda f: f.tbr or 0)
