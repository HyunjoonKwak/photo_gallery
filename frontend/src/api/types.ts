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
  folder: string | null;
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
}

export interface FoldersResponse {
  folders: PhotoFolder[];
}

// --- file operations ---

export interface MoveRequest {
  item_ids: string[];
  dest_folder_id: string;
  copy_mode: boolean;
  target_user?: string;
}

export interface DeleteRequest {
  item_ids: string[];
  target_user?: string;
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
  type: "move" | "copy" | "delete" | "mkdir";
  summary: string;
  status: "done" | "undone" | "failed";
  created_at: string;
  can_undo: boolean;
  target_user: string | null;
}

export interface OperationsResponse {
  operations: OperationEntry[];
}

export interface MembersResponse {
  members: string[];
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
