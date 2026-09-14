// Types matching the FastAPI backend models

export interface FormatInfo {
  format_id: string;
  ext: string;
  resolution: string;
  fps: number | null;
  vcodec: string;
  acodec: string;
  filesize: number | null;
  tbr: number | null;
  vbr: number | null;
  abr: number | null;
  width: number | null;
  height: number | null;
  url: string;
  format_note: string;
  quality: string;
  has_video: boolean;
  has_audio: boolean;
}

export interface MediaInfo {
  id: string;
  title: string;
  description: string;
  thumbnail: string;
  thumbnails: Record<string, any>[];
  duration: number | null;
  duration_string: string;
  view_count: number | null;
  like_count: number | null;
  upload_date: string;
  uploader: string;
  uploader_id: string | null;
  channel: string;
  channel_id: string | null;
  channel_follower_count: number | null;
  tags: string[];
  categories: string[];
  webpage_url: string;
  original_url: string;
  extractor: string;
  extractor_key: string;
  platform: string;
  media_type_detected: string;
  formats: FormatInfo[];
  subtitles: Record<string, any[]>;
  auto_captions: Record<string, any[]>;
  comment_count: number | null;
  age_limit: number | null;
  chapters: Record<string, any>[];
}

export interface ExtractResponse {
  success: boolean;
  media: MediaInfo;
  download_url: string | null;
  message: string;
}

export interface PlaylistItem {
  id: string;
  title: string;
  url: string;
  duration: number | null;
  thumbnail: string;
  uploader: string;
  index: number | null;
}

export interface PlaylistResponse {
  success: boolean;
  title: string;
  description: string;
  uploader: string;
  playlist_count: number;
  items: PlaylistItem[];
}

export interface BatchExtractResponse {
  success: boolean;
  results: ExtractResponse[];
  errors: { url: string; error: string }[];
  total: number;
  successful: number;
  failed: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  yt_dlp_version: string;
  supported_platforms: string[];
  features: string[];
}

export type QualityPreset = "best" | "good" | "worst" | "audio_only" | "custom";
export type MediaType = "all" | "video" | "audio" | "image";
