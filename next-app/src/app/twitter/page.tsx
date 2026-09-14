"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import type {
  ExtractResponse,
  QualityPreset,
  MediaType,
  FormatInfo,
} from "@/lib/types";

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDuration(s: number | null): string {
  if (!s) return "";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function formatNumber(n: number | null): string {
  if (n == null) return "";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n.toLocaleString();
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes >= 1_073_741_824) return (bytes / 1_073_741_824).toFixed(1) + " GB";
  if (bytes >= 1_048_576) return (bytes / 1_048_576).toFixed(0) + " MB";
  if (bytes >= 1024) return (bytes / 1024).toFixed(0) + " KB";
  return bytes + " B";
}

function formatBitrate(kbps: number | null): string {
  if (!kbps) return "";
  if (kbps >= 1000) return (kbps / 1000).toFixed(1) + " Mbps";
  return Math.round(kbps) + " Kbps";
}

// ── Client-side Twitter URL detection ────────────────────────────────────────

const TWITTER_PATTERNS = [
  /twitter\.com/i,
  /x\.com/i,
];

function isTwitterUrl(url: string): boolean {
  return TWITTER_PATTERNS.some((p) => p.test(url));
}

// ── Twitter Page ─────────────────────────────────────────────────────────────

export default function TwitterPage() {
  const [url, setUrl] = useState("");
  const [quality, setQuality] = useState<QualityPreset>("best");
  const [mediaType, setMediaType] = useState<MediaType>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ExtractResponse | null>(null);
  const [showFormats, setShowFormats] = useState(false);
  const [detectedPlatform, setDetectedPlatform] = useState<string | null>(null);

  // Detect platform as user types (client-side check + backend confirm)
  const handleUrlChange = useCallback(async (value: string) => {
    setUrl(value);
    setDetectedPlatform(null);
    if (value.length < 10) return;

    // Quick client-side check
    if (!isTwitterUrl(value)) {
      setDetectedPlatform("not_twitter");
      return;
    }

    // Confirm with backend
    try {
      const data = await api.detect(value);
      setDetectedPlatform(data.platform_key === "twitter" ? "twitter" : "not_twitter");
    } catch {
      setDetectedPlatform(null);
    }
  }, []);

  const handleExtract = useCallback(async () => {
    if (!url.trim()) return;

    // Validate: only Twitter/X URLs allowed
    if (!isTwitterUrl(url)) {
      setError("Only Twitter/X URLs are allowed on this page. Use the main page for other platforms.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    setShowFormats(false);

    try {
      // Final backend validation
      const detection = await api.detect(url.trim());
      if (detection.platform_key !== "twitter") {
        setError(`This URL is from ${detection.platform}, not Twitter/X. Only Twitter URLs are accepted here.`);
        setLoading(false);
        return;
      }

      const data = await api.extract(url.trim(), quality, mediaType);
      if (!data.success) throw new Error(data.message);
      setResult(data);
    } catch (e: any) {
      setError(e.message || "Extraction failed");
    } finally {
      setLoading(false);
    }
  }, [url, quality, mediaType]);

  const isUrlValid = url.length > 10 && isTwitterUrl(url);
  const isUrlWrong = url.length > 10 && !isTwitterUrl(url);

  return (
    <div className="mx-auto max-w-[640px] px-4 py-10">
      {/* Header */}
      <header className="mb-6 text-center">
        <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-sky-50 px-4 py-1.5">
          <span className="text-lg">🐦</span>
          <span className="text-sm font-bold text-sky-600">Twitter / X</span>
        </div>
        <h1 className="text-2xl font-extrabold text-[#1a1a2e]">Twitter Media Downloader</h1>
        <p className="mt-1 text-sm text-gray-500">
          Download videos, GIFs &amp; images from Twitter/X posts
        </p>
      </header>

      {/* URL Input */}
      <div className="mb-3 rounded-xl border border-gray-200 bg-white p-3 shadow-sm transition focus-within:border-sky-500 focus-within:ring-2 focus-within:ring-sky-100">
        <div className="flex items-center gap-2">
          <span className="text-sky-500">🐦</span>
          <input
            type="text"
            value={url}
            onChange={(e) => handleUrlChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleExtract()}
            placeholder="Paste a Twitter/X post URL…"
            className="flex-1 border-none bg-transparent py-2 font-mono text-sm outline-none placeholder:text-gray-400"
          />
          {/* Platform indicator */}
          {detectedPlatform === "twitter" && (
            <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[0.7rem] font-semibold text-sky-600">
              ✓ Twitter
            </span>
          )}
          {isUrlWrong && (
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-[0.7rem] font-semibold text-red-500">
              ✗ Not Twitter
            </span>
          )}
        </div>

        {/* Validation message */}
        {isUrlWrong && (
          <div className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-500">
            ⚠️ Only Twitter/X URLs are accepted here.
            <br />
            <span className="text-gray-400">
              Example: https://twitter.com/user/status/1234567890
            </span>
          </div>
        )}

        <button
          onClick={handleExtract}
          disabled={loading || !url.trim() || !isUrlValid}
          className="mt-2 w-full rounded-lg bg-[#1d9bf0] py-3 text-sm font-bold text-white transition hover:bg-[#1a8cd8] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? (
            <span className="inline-flex items-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Extracting…
            </span>
          ) : (
            "⬇ Download from Twitter"
          )}
        </button>
      </div>

      {/* Options */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select
          value={quality}
          onChange={(e) => setQuality(e.target.value as QualityPreset)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium"
        >
          <option value="best">🏆 Best Quality</option>
          <option value="good">👍 720p</option>
          <option value="worst">💾 Smallest</option>
          <option value="audio_only">🎵 Audio Only</option>
        </select>
        <select
          value={mediaType}
          onChange={(e) => setMediaType(e.target.value as MediaType)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium"
        >
          <option value="all">All Types</option>
          <option value="video">🎬 Video</option>
          <option value="audio">🎵 Audio</option>
          <option value="image">🖼️ Images</option>
        </select>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-600">
          ❌ {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && !result && (
        <div className="mb-4 h-[120px] animate-pulse rounded-xl bg-gray-200" />
      )}

      {/* ── Result ───────────────────────────────────────────────── */}
      {result && !error && (
        <div className="mb-4 overflow-hidden rounded-xl border border-gray-200 bg-white shadow animate-fadeUp">
          <div className="p-4">
            {result.media.thumbnail && (
              <img
                src={result.media.thumbnail}
                alt={result.media.title}
                className="mb-3 h-[180px] w-full rounded-lg object-cover"
                onError={(e) => (e.currentTarget.style.display = "none")}
              />
            )}
            <h3 className="text-base font-bold leading-snug">{result.media.title || "Untitled"}</h3>
            <p className="mt-0.5 text-xs text-gray-500">
              {result.media.uploader || result.media.channel || ""}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="rounded-full bg-sky-50 px-2.5 py-0.5 text-[0.7rem] font-semibold text-sky-600">
                🐦 Twitter/X
              </span>
              {result.media.duration_string && (
                <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-[0.7rem] text-gray-500">
                  ⏱ {result.media.duration_string}
                </span>
              )}
              {result.media.view_count != null && (
                <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-[0.7rem] text-gray-500">
                  👁 {formatNumber(result.media.view_count)} views
                </span>
              )}
              {result.media.like_count != null && (
                <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-[0.7rem] text-gray-500">
                  ❤️ {formatNumber(result.media.like_count)}
                </span>
              )}
            </div>
          </div>

          {/* Download buttons */}
          <div className="flex gap-2 px-4 pb-4">
            {(result.media.webpage_url || result.media.original_url) && (
              <a
                href={api.dlUrl(
                  result.media.webpage_url || result.media.original_url,
                  quality
                )}
                className="rounded-lg bg-[#1d9bf0] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#1a8cd8]"
              >
                ⬇ Download
              </a>
            )}
            {result.media.webpage_url && (
              <a
                href={result.media.webpage_url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-2.5 text-sm font-semibold text-gray-700 transition hover:border-sky-400"
              >
                🔗 Open on Twitter
              </a>
            )}
          </div>

          {/* Formats */}
          {result.media.formats.length > 0 && (
            <div className="border-t border-gray-100 px-4 pb-4 pt-3">
              <button
                onClick={() => setShowFormats(!showFormats)}
                className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 transition hover:text-gray-800"
              >
                <span className={`text-[0.6rem] transition-transform ${showFormats ? "rotate-90" : ""}`}>
                  ▶
                </span>
                Available formats ({result.media.formats.length})
              </button>
              {showFormats && (
                <div className="mt-2 flex flex-col gap-1.5">
                  {result.media.formats
                    .slice()
                    .reverse()
                    .map((f) => (
                      <div
                        key={f.format_id}
                        className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5 transition hover:border-sky-400"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-semibold">
                            {f.resolution || (f.width ? `${f.width}x${f.height}` : f.ext)}
                          </div>
                          <div className="mt-0.5 text-[0.65rem] text-gray-400">
                            {f.format_id} · {f.ext}
                            {formatBitrate(f.tbr || f.abr) ? ` · ${formatBitrate(f.tbr || f.abr)}` : ""}
                            {formatSize(f.filesize) ? ` · ${formatSize(f.filesize)}` : ""}
                          </div>
                        </div>
                        <a
                          href={api.dlUrl(
                            result.media.webpage_url || result.media.original_url,
                            "custom",
                            f.format_id
                          )}
                          className="ml-2 shrink-0 rounded-md bg-[#1d9bf0] px-2.5 py-1 text-[0.7rem] font-semibold text-white transition hover:bg-[#1a8cd8]"
                        >
                          ⬇
                        </a>
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!loading && !result && !error && (
        <div className="py-12 text-center text-gray-400">
          <div className="mb-2 text-3xl opacity-60">🐦</div>
          <h3 className="text-sm font-semibold text-gray-500">Paste a Twitter/X post URL</h3>
          <p className="mt-0.5 text-xs">
            Supports videos, GIFs, images, and polls from any tweet
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2 text-[0.7rem]">
            <span className="rounded-full bg-gray-100 px-3 py-1">📹 Videos</span>
            <span className="rounded-full bg-gray-100 px-3 py-1">🖼️ Images</span>
            <span className="rounded-full bg-gray-100 px-3 py-1">🎵 GIFs</span>
            <span className="rounded-full bg-gray-100 px-3 py-1">🐦 Spaces Audio</span>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="mt-8 border-t border-gray-200 pt-6 text-center text-[0.7rem] text-gray-400">
        <p>
          MediaForge · Twitter extractor · Built with yt-dlp + FastAPI
        </p>
        <div className="mt-2">
          <a href="/" className="text-[var(--accent)] hover:underline">
            ← Back to main extractor
          </a>
        </div>
      </footer>
    </div>
  );
}
