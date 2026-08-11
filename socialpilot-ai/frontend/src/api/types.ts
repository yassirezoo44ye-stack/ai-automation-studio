// Mirrors backend/app/schemas/*.py — keep these in sync by hand for now (Phase 1).
// A generated client (openapi-typescript against /openapi.json) is a natural
// Phase-6+ upgrade once the API surface stabilizes.

export type OrganizationRole = "owner" | "admin" | "editor" | "viewer";

export interface UserPublic {
  id: string;
  email: string;
  full_name: string;
  is_verified: boolean;
  created_at: string;
}

export interface OrganizationMembership {
  id: string;
  name: string;
  slug: string;
  role: OrganizationRole;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  csrf_token: string;
  user: UserPublic;
  organizations: OrganizationMembership[];
}

export interface MeResponse {
  user: UserPublic;
  organizations: OrganizationMembership[];
}

export interface ApiErrorBody {
  detail: string | { msg: string; loc: (string | number)[] }[];
  code?: string;
}
