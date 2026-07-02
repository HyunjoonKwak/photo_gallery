export type Role = "admin" | "member";
export type Space = "team" | "personal";

export interface UserInfo {
  account: string;
  role: Role;
  can_browse_homes: boolean;
  mock_mode: boolean;
}

export interface PhotoBucket {
  day: string; // YYYY-MM-DD
  count: number;
}

export interface BucketsResponse {
  space: Space;
  buckets: PhotoBucket[];
}

export interface PhotoItem {
  id: string;
  filename: string;
  taken_at: string;
  width: number;
  height: number;
  size: number | null;
  cache_key: string;
  placeholder_color: string | null;
  /** base64 thumbhash (blur placeholder) — present once the dedup scan has
   * hashed the item; decoded client-side. */
  thumbhash: string | null;
  folder: string | null;
  /** Set client-side when the item's space differs from the global scope
   * (folder view can show personal folders while scope is team). */
  space?: Space;
}

export interface BucketItemsResponse {
  space: Space;
  day: string;
  items: PhotoItem[];
}

export interface PhotoFolder {
  id: string;
  name: string;
  space: Space;
  parent_id: string | null;
  depth: number;
}

export interface FoldersResponse {
  folders: PhotoFolder[];
}

export interface FolderCountsResponse {
  /** folder id → direct item count; failed ids are omitted. */
  counts: Record<string, number>;
}

/** Synology Photos 내장 AI의 얼굴 그룹 (3단계 분류). */
export interface PersonInfo {
  id: string;
  space: Space;
  name: string; // "" = 이름 미지정 그룹
  item_count: number | null;
  cover_item_id: string | null;
  cover_cache_key: string | null;
}

export interface PersonsResponse {
  space: Space;
  persons: PersonInfo[];
}

/** GPS 지오코딩 기반 장소 그룹. */
export interface PlaceInfo {
  id: string;
  space: Space;
  name: string;
  item_count: number | null;
}

export interface PlacesResponse {
  space: Space;
  places: PlaceInfo[];
}

/** 라이트박스 정보 패널용 온디맨드 상세 (폴더 경로/EXIF/촬영 위치). */
export interface ItemDetail {
  id: string;
  folder: string | null;
  /** keys: camera, lens, aperture, exposure_time, iso, focal_length */
  exif: Record<string, string>;
  address: string | null;
}

// --- file operations ---

export interface MoveRequest {
  space: Space;
  item_ids: string[];
  dest_folder_id: string;
  copy_mode: boolean;
  target_user?: string;
  /** Client-generated key for count-based progress polling. */
  progress_key?: string;
}

export interface DeleteRequest {
  space: Space;
  item_ids: string[];
  target_user?: string;
  progress_key?: string;
}

export interface ProgressResponse {
  active: boolean;
  done: number;
  total: number;
  label: string;
}

export interface CreateFolderRequest {
  space: Space;
  name: string;
  target_user?: string;
}

export interface AffectedDay {
  space: Space;
  day: string;
}

export interface OperationResponse {
  operation_id: number;
  summary: string;
  affected: AffectedDay[];
  undoable: boolean;
  folder: PhotoFolder | null;
}

export interface OperationEntry {
  id: number;
  type: "move" | "copy" | "delete" | "mkdir" | "empty_trash";
  summary: string;
  /** purged = 휴지통 비우기로 undo 소멸 */
  status: "done" | "undone" | "failed" | "purged";
  created_at: string;
  can_undo: boolean;
  target_user: string | null;
}

export interface TrashStatsResponse {
  operations: number;
  items: number;
}

export interface OperationsResponse {
  operations: OperationEntry[];
}

export interface MembersResponse {
  members: string[];
}

// --- duplicate detection (phase 2) ---

export interface DedupJob {
  id: number;
  space: Space;
  status: "running" | "done" | "failed" | "cancelled";
  processed: number;
  total: number;
  error: string | null;
  updated_at: string;
}

export interface DedupJobResponse {
  job: DedupJob | null;
}

export interface DedupItem extends PhotoItem {
  space: Space;
}

export interface DedupGroup {
  id: string;
  kind: "exact" | "similar";
  items: DedupItem[];
  reference_id: string;
  wasted_bytes: number;
}

export interface DedupGroupsResponse {
  space: Space;
  threshold: number;
  groups: DedupGroup[]; // top-N by wasted bytes
  total_groups: number;
  total_wasted_bytes: number; // across all groups
  scanned: boolean;
}

export interface EndpointInfo {
  api: string;
  path: string;
  min_version: number;
  max_version: number;
  available: boolean;
}

export interface ApiInfoResponse {
  dsm_webapi_base: string;
  endpoints: EndpointInfo[];
}

export interface LoginRequest {
  account: string;
  passwd: string;
  otp_code?: string;
}
