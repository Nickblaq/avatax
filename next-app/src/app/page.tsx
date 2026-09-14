"use client";

import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import type {
  ExtractResponse,
  PlaylistResponse,
  BatchExtractResponse,
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

const PLATFORM_EMOJI: Record<string, string> = {
  YouTube: "▶️",
  "Twitter/X": "🐦",
  Instagram: "📸",
  TikTok: "🎵",
  Facebook: "👤",
  Vimeo: "🎥",
  Twitch: "🎮",
  SoundCloud: "☁️",
  Reddit: "🔗",
  Pornhub: "🔞",
  XVideos: "🔞",
  xHamster: "🔞",
};

function platformEmoji(p: string): string {
  return PLATFORM_EMOJI[p] || "🌐";
}

function formatType(f: FormatInfo): "muxed" | "video" | "audio" {
  const hasV = f.has_video && f.vcodec !== "none" && f.vcodec !== "";
  const hasA = f.has_audio && f.acodec !== "none" && f.acodec !== "";
  if (hasV && hasA) return "muxed";
  if (hasV) return "video";
  return "audio";
}

// ── Main Page ────────────────────────────────────────────────────────────────

type Tab = "single" | "batch" | "playlist";

export default function Home() {
  const [tab, setTab] = useState<Tab>("single");
  const [url, setUrl] = useState("");
  const [batchUrls, setBatchUrls] = useState("");
  const [quality, setQuality] = useState<QualityPreset>("best");
  const [mediaType, setMediaType] = useState<MediaType>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [result, setResult] = useState<ExtractResponse | null>(null);
  const [playlist, setPlaylist] = useState<PlaylistResponse | null>(null);
  const [batch, setBatch] = useState<BatchExtractResponse | null>(null);
  const [showFormats, setShowFormats] = useState(false);

  const reset = useCallback(() => {
    setResult(null);
    setPlaylist(null);
    setBatch(null);
    setError(null);
    setShowFormats(false);
  }, []);

  const handleExtract = useCallback(async () => {
    if (!url.trim()) return;
    setLoading(true);
    reset();
    try {
      const data = await api.extract(url.trim(), quality, mediaType);
      if (!data.success) throw new Error(data.message);
      setResult(data);
    } catch (e: any) {
      setError(e.message || "Extraction failed");
    } finally {
      setLoading(false);
    }
  }, [url, quality, mediaType, reset]);

  const handleBatch = useCallback(async () => {
    const urls = batchUrls
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean);
    if (!urls.length) return;
    if (urls.length > 20) {
      setError("Maximum 20 URLs");
      return;
    }
    setLoading(true);
    reset();
    try {
      const data = await api.batchExtract(urls, quality, mediaType);
      setBatch(data);
    } catch (e: any) {
      setError(e.message || "Batch failed");
    } finally {
      setLoading(false);
    }
  }, [batchUrls, quality, mediaType, reset]);

  const handlePlaylist = useCallback(async () => {
    if (!url.trim()) return;
    setLoading(true);
    reset();
    try {
      const data = await api.playlist(url.trim());
      if (!data.success) throw new Error("Playlist extraction failed");
      setPlaylist(data);
    } catch (e: any) {
      setError(e.message || "Playlist failed");
    } finally {
      setLoading(false);
    }
  }, [url, reset]);

  const submit = useCallback(() => {
    if (tab === "batch") handleBatch();
    else if (tab === "playlist") handlePlaylist();
    else handleExtract();
  }, [tab, handleBatch, handlePlaylist, handleExtract]);

  return (
    <div className="mx-auto max-w-[640px] px-4 py-10">
      {/* Hero */}
      <header className="mb-6 text-center">
        <h1 className="text-2xl font-extrabold text-[var(--accent)]">⚡ MediaForge</h1>
        <p className="mt-1 text-sm text-gray-500">
          Download video, audio &amp; images from 30+ platforms
        </p>
      </header>

      {/* Tabs */}
      <div className="mb-4 flex gap-1 rounded-lg bg-gray-100 p-1">
        {(["single", "batch", "playlist"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => {
              setTab(t);
              reset();
            }}
            className={`flex-1 rounded-md px-3 py-2 text-xs font-semibold transition ${
              tab === t
                ? "bg-[var(--accent)] text-white shadow"
                : "text-gray-500 hover:text-gray-800"
            }`}
          >
            {t === "single" ? "Single" : t === "batch" ? "Batch" : "Playlist"}
          </button>
        ))}
      </div>

      {/* URL Input — Single */}
      {tab === "single" && (
        <div className="mb-3 rounded-xl border border-gray-200 bg-white p-3 shadow-sm focus-within:border-[var(--accent)] focus-within:ring-2 focus-within:ring-[var(--accent-light)]">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Paste any media URL…"
            className="w-full border-none bg-transparent py-2 font-mono text-sm outline-none placeholder:text-gray-400"
          />
          <button
            onClick={submit}
            disabled={loading || !url.trim()}
            className="mt-2 w-full rounded-lg bg-[var(--accent)] py-3 text-sm font-bold text-white transition hover:bg-[var(--accent-hover)] disabled:opacity-50"
          >
            {loading ? "Extracting…" : "Extract"}
          </button>
        </div>
      )}

      {/* Batch */}
      {tab === "batch" && (
        <div className="mb-3">
          <textarea
            value={batchUrls}
            onChange={(e) => setBatchUrls(e.target.value)}
            placeholder={"One URL per line (max 20)…"}
            className="mb-2 w-full min-h-[120px] rounded-xl border border-gray-200 bg-white p-3 text-sm outline-none focus:border-[var(--accent)]"
          />
          <button
            onClick={submit}
            disabled={loading || !batchUrls.trim()}
            className="w-full rounded-lg bg-[var(--accent)] py-3 text-sm font-bold text-white transition hover:bg-[var(--accent-hover)] disabled:opacity-50"
          >
            {loading ? "Extracting…" : "Extract All"}
          </button>
        </div>
      )}

      {/* Playlist */}
      {tab === "playlist" && (
        <div className="mb-3 rounded-xl border border-gray-200 bg-white p-3 shadow-sm focus-within:border-[var(--accent)] focus-within:ring-2 focus-within:ring-[var(--accent-light)]">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Paste playlist URL…"
            className="w-full border-none bg-transparent py-2 font-mono text-sm outline-none placeholder:text-gray-400"
          />
          <button
            onClick={submit}
            disabled={loading || !url.trim()}
            className="mt-2 w-full rounded-lg bg-[var(--accent)] py-3 text-sm font-bold text-white transition hover:bg-[var(--accent-hover)] disabled:opacity-50"
          >
            {loading ? "Loading…" : "Extract Playlist"}
          </button>
        </div>
      )}

      {/* Options */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select
          value={quality}
          onChange={(e) => setQuality(e.target.value as QualityPreset)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium"
        >
          <option value="best">🏆 Best</option>
          <option value="good">👍 720p</option>
          <option value="worst">💾 Smallest</option>
          <option value="audio_only">🎵 Audio</option>
        </select>
        <select
          value={mediaType}
          onChange={(e) => setMediaType(e.target.value as MediaType)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium"
        >
          <option value="all">All</option>
          <option value="video">Video</option>
          <option value="audio">Audio</option>
          <option value="image">Images</option>
        </select>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-600">
          ❌ {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && !result && !playlist && !batch && (
        <div className="mb-4 h-[120px] animate-pulse rounded-xl bg-gray-200" />
      )}

      {/* ── Single Result ─────────────────────────────────────────── */}
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
              <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[0.7rem] font-semibold text-[var(--accent)]">
                {platformEmoji(result.media.platform)} {result.media.platform}
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
                className="rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[var(--accent-hover)]"
              >
                ⬇ Download
              </a>
            )}
            {result.media.webpage_url && (
              <a
                href={result.media.webpage_url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-2.5 text-sm font-semibold text-gray-700 transition hover:border-[var(--accent)]"
              >
                🔗 Original
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
                        className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5 transition hover:border-[var(--accent)]"
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
                          className="ml-2 shrink-0 rounded-md bg-[var(--accent)] px-2.5 py-1 text-[0.7rem] font-semibold text-white transition hover:bg-[var(--accent-hover)]"
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

      {/* ── Playlist Result ───────────────────────────────────────── */}
      {playlist && !error && (
        <div className="mb-4 overflow-hidden rounded-xl border border-gray-200 bg-white shadow animate-fadeUp">
          <div className="p-4">
            <h3 className="text-base font-bold">{playlist.title || "Playlist"}</h3>
            <div className="mt-1 flex gap-1.5">
              {playlist.uploader && (
                <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[0.7rem] font-semibold text-[var(--accent)]">
                  👤 {playlist.uploader}
                </span>
              )}
              <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-[0.7rem] text-gray-500">
                {playlist.playlist_count} items
              </span>
            </div>
          </div>
          <div className="max-h-[400px] overflow-y-auto px-4 pb-4">
            {playlist.items.map((item) => (
              <div
                key={item.id || item.index}
                onClick={() => {
                  setUrl(item.url);
                  setTab("single");
                  handleExtract();
                }}
                className="mb-1.5 flex cursor-pointer items-center gap-2.5 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 transition hover:border-[var(--accent)]"
              >
                <span className="min-w-[24px] text-center text-[0.7rem] font-bold text-gray-400">
                  {item.index}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs">
                  {item.title || item.id}
                </span>
                <span className="shrink-0 font-mono text-[0.65rem] text-gray-400">
                  {formatDuration(item.duration)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Batch Result ─────────────────────────────────────────── */}
      {batch && !error && (
        <div className="animate-fadeUp">
          <div
            className={`mb-3 rounded-lg p-2.5 text-center text-xs font-medium ${
              batch.failed > 0
                ? "border border-red-200 bg-red-50 text-red-600"
                : "border border-green-200 bg-green-50 text-green-600"
            }`}
          >
            ✅ {batch.successful} OK · ❌ {batch.failed} failed
          </div>
          {batch.results.map((r, i) => (
            <div key={i} className="mb-2 overflow-hidden rounded-lg border border-gray-200 bg-white">
              <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-3 py-1.5 text-[0.7rem] text-gray-400">
                <span className="truncate max-w-[70%]">{r.media?.webpage_url || ""}</span>
                <span>{r.success ? "✅" : "❌"}</span>
              </div>
              {r.success ? (
                <div className="p-3">
                  <div className="text-xs font-semibold">{r.media?.title || "Untitled"}</div>
                  {(r.media?.webpage_url || r.media?.original_url) && (
                    <a
                      href={api.dlUrl(
                        r.media!.webpage_url || r.media!.original_url,
                        "best"
                      )}
                      className="mt-1.5 inline-block rounded-md bg-indigo-50 px-3 py-1 text-[0.75rem] font-semibold text-[var(--accent)]"
                    >
                      ⬇ Download
                    </a>
                  )}
                </div>
              ) : (
                <div className="p-3 text-xs text-red-500">{r.message || "Failed"}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && !result && !playlist && !batch && !error && (
        <div className="py-12 text-center text-gray-400">
          <div className="mb-2 text-3xl opacity-60">⚡</div>
          <h3 className="text-sm font-semibold text-gray-500">Paste a URL to get started</h3>
          <p className="mt-0.5 text-xs">
            YouTube, Twitter, Instagram, TikTok, Reddit, Pornhub &amp; more
          </p>
        </div>
      )}

      {/* Footer */}
      <footer className="mt-8 border-t border-gray-200 pt-6 text-center text-[0.7rem] text-gray-400">
        <p>
          MediaForge · Built with{" "}
          <a
            href="https://github.com/yt-dlp/yt-dlp"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--accent)] hover:underline"
          >
            yt-dlp
          </a>{" "}
          + FastAPI
        </p>
        <div className="mt-2 flex justify-center gap-3">
          <a href="/twitter" className="text-sky-500 hover:underline">
            🐦 Twitter Extractor
          </a>
        </div>
      </footer>
    </div>
  );
}
