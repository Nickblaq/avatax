"""
MediaForge — Advanced Media Extractor API
Built on yt-dlp 2026.08.19+ and FastAPI.
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
import yt_dlp
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from models import (
    BatchExtractRequest,
    BatchExtractResponse,
    ErrorResponse,
    ExtractRequest,
    ExtractResponse,
    HealthResponse,
    PlaylistRequest,
    PlaylistResponse,
)
from extractor import (
    SUPPORTED_PLATFORMS,
    batch_extract,
    detect_platform,
    extract_media,
    extract_playlist,
    get_format_url,
)

# ── App Lifespan ─────────────────────────────────────────────────────────────

_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.time()
    yield


# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="MediaForge",
    description=(
        "Advanced multi-platform media extractor API. "
        "Extract video, audio, images, and metadata from 30+ platforms "
        "including YouTube, Twitter/X, Instagram, TikTok, Reddit, "
        "Facebook, Vimeo, Twitch, Pornhub, and more."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Error Handlers ───────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Any, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error=str(exc), detail="An unexpected error occurred").model_dump(),
    )


# ── Health & Info ────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_ui():
    """Serve the web UI."""
    return FileResponse("static/index.html")


@app.get("/health", response_model=HealthResponse, tags=["Info"])
async def health_check():
    """Health check with service info."""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        yt_dlp_version=yt_dlp.version.__version__,
        supported_platforms=SUPPORTED_PLATFORMS,
        features=[
            "multi_platform_extraction",
            "quality_selection",
            "audio_extraction",
            "video_extraction",
            "thumbnail_extraction",
            "playlist_extraction",
            "batch_extraction",
            "format_listing",
            "subtitle_extraction",
            "metadata_extraction",
            "gallery_extraction",
            "age_restriction_bypass",
            "geo_bypass",
        ],
    )


@app.get("/platforms", tags=["Info"])
async def list_platforms():
    """List all supported platforms."""
    return {
        "platforms": SUPPORTED_PLATFORMS,
        "count": len(SUPPORTED_PLATFORMS),
        "note": "Any URL supported by yt-dlp works, even if not listed here.",
    }


# ── Core Extraction ──────────────────────────────────────────────────────────

@app.post("/extract", response_model=ExtractResponse, tags=["Extract"])
async def extract_media_endpoint(request: ExtractRequest):
    """
    Extract media information and formats from a URL.

    Returns metadata, available formats, and a direct download URL
    without downloading the file.
    """
    try:
        result = extract_media(request)
        return result
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")


@app.post("/extract/batch", response_model=BatchExtractResponse, tags=["Extract"])
async def batch_extract_endpoint(request: BatchExtractRequest):
    """
    Extract media info from multiple URLs in one request.

    Maximum 20 URLs per batch.
    """
    try:
        return batch_extract(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch extraction failed: {e}")


@app.get("/extract/url", response_model=ExtractResponse, tags=["Extract"])
async def extract_media_quick(
    url: str = Query(..., description="Media URL to extract"),
    media_type: str = Query("all", description="Filter: video, audio, image, all"),
    quality: str = Query("best", description="Quality: best, good, worst, audio_only"),
):
    """
    Quick extraction via GET — paste a URL and get media info + download link.
    Useful for browser-based integrations.
    """
    try:
        req = ExtractRequest(url=url, media_type=media_type, quality=quality)  # type: ignore[arg-type]
        result = extract_media(req)
        return result
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")


# ── Proxy Download ───────────────────────────────────────────────────────────

# Shared httpx client — stays alive across requests, avoids connection churn
_http_client: httpx.AsyncClient | None = None


async def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=15.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            },
        )
    return _http_client


@app.get("/dl", tags=["Download"])
async def proxy_download(
    url: str = Query(..., description="Direct media file URL to proxy-download"),
    filename: str = Query(default="", description="Suggested filename"),
):
    """
    Proxy-download a file through the server with proper Content-Disposition.

    This forces the browser to download instead of streaming.
    """
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # Derive filename from URL if not provided
    if not filename:
        parsed = urlparse(url)
        path_part = unquote(parsed.path)
        filename = path_part.split("/")[-1] if "/" in path_part else "download"
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        if not filename or filename == "download":
            filename = "media_download"

    try:
        client = await _get_http_client()

        parsed_url = urlparse(url)
        referer = f"{parsed_url.scheme}://{parsed_url.netloc}/"

        response = await client.get(
            url,
            headers={
                "Referer": referer,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
            },
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Upstream returned {response.status_code} for {url[:120]}",
            )

        content_type = response.headers.get("content-type", "application/octet-stream")
        content_length = response.headers.get("content-length")

        # Read full content into memory so StreamingResponse has reliable access
        content = response.content

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Content-Type-Options": "nosniff",
            "Pragma": "no-cache",
        }
        if content_length:
            headers["Content-Length"] = content_length
        else:
            headers["Content-Length"] = str(len(content))

        async def generate():
            yield content

        return StreamingResponse(
            generate(),
            status_code=200,
            headers=headers,
            media_type=content_type,
        )

    except HTTPException:
        raise
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch file: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")


@app.get("/dl/format", tags=["Download"])
async def proxy_download_format(
    source_url: str = Query(..., description="Original media page URL"),
    format_id: str = Query(..., description="yt-dlp format ID to download"),
    filename: str = Query(default="", description="Suggested filename"),
):
    """
    Download a specific format from a media URL via yt-dlp.

    Uses yt-dlp to resolve the exact format URL then proxies the download.
    """
    try:
        from models import ExtractRequest, QualityPreset
        req = ExtractRequest(url=source_url, format_id=format_id, quality=QualityPreset.CUSTOM)
        fmt_url = get_format_url(req, format_id)
        if not fmt_url:
            raise HTTPException(status_code=404, detail=f"Format '{format_id}' not found for {source_url}")
        return await proxy_download(url=fmt_url, filename=filename)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Format download failed: {e}")


@app.get("/dl/test", tags=["Download"])
async def proxy_download_test(
    url: str = Query(..., description="URL to test fetching"),
):
    """
    Debug endpoint — tests fetching a URL and returns metadata.
    Use this to verify the proxy can reach a URL before downloading.
    """
    try:
        client = await _get_http_client()
        response = await client.head(url, follow_redirects=True)
        return {
            "status": response.status_code,
            "content_type": response.headers.get("content-type", "unknown"),
            "content_length": response.headers.get("content-length", "unknown"),
            "final_url": str(response.url),
            "headers": dict(response.headers),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Direct Download (legacy) ─────────────────────────────────────────────────

@app.post("/download", tags=["Download"])
async def download_media(request: DownloadRequest):
    """
    Download media and return a proxy download URL.

    Returns a /dl endpoint URL that forces browser download.
    """
    try:
        from models import MediaType, QualityPreset
        req = ExtractRequest(
            url=request.url,
            media_type=request.media_type,
            quality=request.quality,
            format_id=request.format_id,
        )
        result = extract_media(req)
        if not result.success or not result.download_url:
            raise HTTPException(status_code=404, detail="Could not generate download URL")

        # Build proxy URL so browser downloads instead of streams
        import urllib.parse
        proxy_url = f"/dl?url={urllib.parse.quote(result.download_url, safe='')}&filename={urllib.parse.quote(result.media.title or 'download', safe='')}"

        return {
            "success": True,
            "download_url": result.download_url,
            "proxy_download_url": proxy_url,
            "title": result.media.title,
            "format": result.media.formats[-1].format_id if result.media.formats else "",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")


@app.get("/download/redirect", tags=["Download"])
async def download_redirect(
    url: str = Query(..., description="Media URL"),
    quality: str = Query("best", description="Quality preset"),
):
    """
    Direct redirect to the best-quality media file.

    Returns a 307 redirect to the actual video/audio URL.
    Useful for embedding or direct playback.
    """
    try:
        from models import ExtractRequest
        req = ExtractRequest(url=url, quality=quality)  # type: ignore[arg-type]
        result = extract_media(req)
        if not result.success or not result.download_url:
            raise HTTPException(status_code=404, detail="No direct URL available for this media")
        return RedirectResponse(url=result.download_url, status_code=307)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Format Listing ───────────────────────────────────────────────────────────

@app.get("/formats", tags=["Formats"])
async def list_formats(
    url: str = Query(..., description="Media URL"),
    media_type: str = Query("all", description="Filter: video, audio, image, all"),
):
    """
    List all available formats for a URL.

    Returns format details including resolution, codec, bitrate,
    and direct URLs for each available format.
    """
    try:
        from models import ExtractRequest, MediaType
        req = ExtractRequest(url=url, media_type=MediaType(media_type))  # type: ignore[arg-type]
        result = extract_media(req)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)
        return {
            "success": True,
            "title": result.media.title,
            "platform": result.media.platform,
            "duration": result.media.duration_string,
            "formats": [f.model_dump() for f in result.media.formats],
            "total_formats": len(result.media.formats),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Audio Extraction ─────────────────────────────────────────────────────────

@app.get("/audio", tags=["Audio"])
async def extract_audio(
    url: str = Query(..., description="Media URL to extract audio from"),
    codec: str = Query("best", description="Preferred codec: best, mp3, m4a, opus, flac"),
):
    """
    Extract audio-only from any supported media URL.

    Returns metadata and a direct download URL for the audio stream.
    """
    try:
        from models import ExtractRequest, QualityPreset
        req = ExtractRequest(url=url, quality=QualityPreset.AUDIO_ONLY)
        result = extract_media(req)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)

        audio_formats = [f for f in result.media.formats if f.has_audio]

        # Filter by preferred codec if specified
        if codec != "best" and audio_formats:
            codec_map = {
                "mp3": ["mp3", "mp3a"],
                "m4a": ["mp4a", "m4a", "aac"],
                "opus": ["opus"],
                "flac": ["flac", "fLaC"],
            }
            preferred = codec_map.get(codec, [codec])
            filtered = [f for f in audio_formats if any(p in f.acodec.lower() for p in preferred)]
            if filtered:
                audio_formats = filtered

        best = max(audio_formats, key=lambda f: f.abr or 0) if audio_formats else None

        return {
            "success": True,
            "title": result.media.title,
            "platform": result.media.platform,
            "duration": result.media.duration_string,
            "uploader": result.media.uploader,
            "thumbnail": result.media.thumbnail,
            "audio_formats": [f.model_dump() for f in audio_formats],
            "best_audio_url": best.url if best else None,
            "best_audio_bitrate": f"{best.abr:.0f}kbps" if best and best.abr else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Thumbnail Extraction ─────────────────────────────────────────────────────

@app.get("/thumbnail", tags=["Thumbnails"])
async def extract_thumbnail(
    url: str = Query(..., description="Media URL"),
    index: int = Query(0, description="Thumbnail index (0 = best)"),
):
    """
    Extract thumbnails for a media URL.

    Returns all available thumbnails with their URLs and dimensions.
    """
    try:
        from models import ExtractRequest
        req = ExtractRequest(url=url)
        result = extract_media(req)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)

        thumbs = result.media.thumbnails
        selected = thumbs[index] if index < len(thumbs) else (thumbs[-1] if thumbs else {})

        return {
            "success": True,
            "title": result.media.title,
            "platform": result.media.platform,
            "selected_thumbnail": selected,
            "all_thumbnails": thumbs,
            "total_thumbnails": len(thumbs),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Subtitle Extraction ──────────────────────────────────────────────────────

@app.get("/subtitles", tags=["Subtitles"])
async def extract_subtitles(
    url: str = Query(..., description="Media URL"),
    lang: str = Query("en", description="Language code (en, es, fr, etc.)"),
):
    """
    Extract available subtitles and auto-captions for a media URL.
    """
    try:
        from models import ExtractRequest
        req = ExtractRequest(url=url, include_subtitles=True)
        result = extract_media(req)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)

        subtitles = result.media.subtitles
        auto_captions = result.media.auto_captions

        # Find requested language
        sub_entry = subtitles.get(lang, subtitles.get("en", []))
        auto_entry = auto_captions.get(lang, auto_captions.get("en", []))

        return {
            "success": True,
            "title": result.media.title,
            "platform": result.media.platform,
            "available_languages": list(subtitles.keys()),
            "auto_caption_languages": list(auto_captions.keys()),
            "requested_subtitles": sub_entry,
            "requested_auto_captions": auto_entry,
            "has_subtitles": bool(subtitles),
            "has_auto_captions": bool(auto_captions),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Playlist Extraction ──────────────────────────────────────────────────────

@app.post("/playlist", response_model=PlaylistResponse, tags=["Playlist"])
async def extract_playlist_endpoint(request: PlaylistRequest):
    """
    Extract playlist metadata and items.

    Returns playlist info with all video entries.
    """
    try:
        return extract_playlist(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Playlist extraction failed: {e}")


@app.get("/playlist", response_model=PlaylistResponse, tags=["Playlist"])
async def extract_playlist_quick(
    url: str = Query(..., description="Playlist URL"),
    limit: int = Query(50, ge=1, le=500, description="Max items"),
):
    """Quick playlist extraction via GET."""
    try:
        req = PlaylistRequest(url=url, limit=limit)
        return extract_playlist(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Playlist extraction failed: {e}")


# ── Metadata Only ────────────────────────────────────────────────────────────

@app.get("/metadata", tags=["Metadata"])
async def extract_metadata(
    url: str = Query(..., description="Media URL"),
):
    """
    Extract only metadata (title, description, stats) without format info.

    Faster than /extract when you only need metadata.
    """
    try:
        from models import ExtractRequest
        req = ExtractRequest(url=url)
        result = extract_media(req)
        if not result.success:
            raise HTTPException(status_code=404, detail=result.message)

        m = result.media
        return {
            "success": True,
            "id": m.id,
            "title": m.title,
            "description": m.description,
            "thumbnail": m.thumbnail,
            "duration": m.duration,
            "duration_string": m.duration_string,
            "view_count": m.view_count,
            "like_count": m.like_count,
            "upload_date": m.upload_date,
            "uploader": m.uploader,
            "channel": m.channel,
            "platform": m.platform,
            "media_type": m.media_type_detected,
            "tags": m.tags,
            "categories": m.categories,
            "comment_count": m.comment_count,
            "age_limit": m.age_limit,
            "chapters": m.chapters,
            "webpage_url": m.webpage_url,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Platform Detection ───────────────────────────────────────────────────────

@app.get("/detect", tags=["Info"])
async def detect_platform_endpoint(
    url: str = Query(..., description="URL to identify the platform"),
):
    """Detect which platform a URL belongs to."""
    name, key = detect_platform(url)
    return {
        "url": url,
        "platform": name,
        "platform_key": key,
        "is_supported": key in SUPPORTED_PLATFORMS,
    }


# ── Info / Metadata ──────────────────────────────────────────────────────────

@app.get("/info", tags=["Info"])
async def info():
    """API information and capabilities."""
    return {
        "name": "MediaForge",
        "version": "1.0.0",
        "description": "Advanced multi-platform media extractor API",
        "yt_dlp_version": yt_dlp.version.__version__,
        "endpoints": {
            "health": "GET /health — Service health and platform list",
            "extract": "POST /extract — Full media extraction with formats",
            "extract_quick": "GET /extract/url?url=... — Quick extraction via GET",
            "batch": "POST /extract/batch — Extract from multiple URLs",
            "download": "POST /download — Get proxy download URL",
            "dl": "GET /dl?url=...&filename=... — Proxy download with forced download",
            "dl_format": "GET /dl/format?source_url=...&format_id=... — Download specific format",
            "download_redirect": "GET /download/redirect?url=... — Redirect to media file",
            "formats": "GET /formats?url=... — List all available formats",
            "audio": "GET /audio?url=... — Extract audio-only streams",
            "thumbnail": "GET /thumbnail?url=... — Extract thumbnails",
            "subtitles": "GET /subtitles?url=... — Extract subtitles/captions",
            "playlist": "GET|POST /playlist — Extract playlist items",
            "metadata": "GET /metadata?url=... — Metadata only (fast)",
            "detect": "GET /detect?url=... — Detect platform from URL",
            "platforms": "GET /platforms — List supported platforms",
        },
        "quality_presets": ["best", "good", "worst", "audio_only", "custom"],
        "supported_media_types": ["video", "audio", "image", "all"],
    }


# ── Mount Static Files ─────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Uvicorn Entry ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
