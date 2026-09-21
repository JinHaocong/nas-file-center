export interface MediaAsset {
  id: number;
  indexed_path_id: number;
  root_key: string;
  path: string;
  relative_path: string;
  basename: string;
  size: number;
  mtime_ns: number;
  media_kind: 'image' | 'video';
  width: number | null;
  height: number | null;
  format: string | null;
  date_taken: string | null;
  camera: string | null;
  orientation: number | null;
  duration_seconds: number | null;
  codec: string | null;
  bitrate: number | null;
  fps: number | null;
  audio_codec: string | null;
  integrity_status: 'healthy' | 'corrupt' | 'unknown';
  integrity_reason_code: string | null;
  integrity_detail: string | null;
  can_direct_delete: boolean;
  probed_at: string | null;
}

export interface MediaSummary {
  total: number;
  image: number;
  video: number;
  healthy: number;
  corrupt: number;
  unknown: number;
}

export interface CorruptDeletePreviewItem {
  media_asset_id: number;
  indexed_path_id?: number;
  path?: string;
  size?: number;
  media_kind?: 'image' | 'video';
  integrity_status?: string;
  integrity_reason_code?: string | null;
  evidence_digest?: string;
  eligible: boolean;
  blockers: string[];
}

export interface CorruptDeletePreview {
  semantics: string;
  selected_media_asset_ids: number[];
  items: CorruptDeletePreviewItem[];
  eligible_count: number;
  blocked_count: number;
  total_bytes: number;
  preview_digest: string;
}
