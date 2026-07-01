export type Role = "admin" | "member";

export interface UserInfo {
  account: string;
  role: Role;
  can_browse_homes: boolean;
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
