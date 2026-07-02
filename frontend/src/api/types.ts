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
