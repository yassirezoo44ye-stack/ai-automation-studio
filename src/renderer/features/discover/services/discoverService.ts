import type {
  FlowCreation,
  CreateCreationPayload,
  UpdateCreationPayload,
  CreationFeedResponse,
  CreationType,
} from "../types/creation.types";

const BASE = "/api";

function headers(orgId?: string): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (orgId) h["X-Organization-Id"] = orgId;
  const token =
    localStorage.getItem("sub_token") ||
    sessionStorage.getItem("sub_token") ||
    "";
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}

/** Public discover feed — no auth needed */
export async function fetchDiscoverFeed(
  opts: { type?: CreationType; limit?: number; offset?: number } = {}
): Promise<CreationFeedResponse> {
  const params = new URLSearchParams();
  if (opts.type)   params.set("type",   opts.type);
  if (opts.limit)  params.set("limit",  String(opts.limit));
  if (opts.offset) params.set("offset", String(opts.offset));
  const qs = params.toString() ? `?${params}` : "";
  const res = await fetch(`${BASE}/discover${qs}`);
  return handleResponse<CreationFeedResponse>(res);
}

/** My org's creations */
export async function fetchMyCreations(
  orgId: string,
  opts: { type?: CreationType; limit?: number; offset?: number } = {}
): Promise<CreationFeedResponse> {
  const params = new URLSearchParams();
  if (opts.type)   params.set("type",   opts.type);
  if (opts.limit)  params.set("limit",  String(opts.limit));
  if (opts.offset) params.set("offset", String(opts.offset));
  const qs = params.toString() ? `?${params}` : "";
  const res = await fetch(`${BASE}/discover/mine${qs}`, { headers: headers(orgId) });
  return handleResponse<CreationFeedResponse>(res);
}

/** Create a new creation card */
export async function createCreation(
  orgId: string,
  payload: CreateCreationPayload
): Promise<FlowCreation> {
  const res = await fetch(`${BASE}/creations`, {
    method: "POST",
    headers: headers(orgId),
    body: JSON.stringify(payload),
  });
  return handleResponse<FlowCreation>(res);
}

/** Get one creation */
export async function getCreation(
  id: string,
  orgId?: string
): Promise<FlowCreation> {
  const res = await fetch(`${BASE}/creations/${id}`, { headers: headers(orgId) });
  return handleResponse<FlowCreation>(res);
}

/** Update metadata */
export async function updateCreation(
  id: string,
  orgId: string,
  payload: UpdateCreationPayload
): Promise<FlowCreation> {
  const res = await fetch(`${BASE}/creations/${id}`, {
    method: "PATCH",
    headers: headers(orgId),
    body: JSON.stringify(payload),
  });
  return handleResponse<FlowCreation>(res);
}

/** Delete */
export async function deleteCreation(id: string, orgId: string): Promise<void> {
  const res = await fetch(`${BASE}/creations/${id}`, {
    method: "DELETE",
    headers: headers(orgId),
  });
  return handleResponse<void>(res);
}

/** Publish to public feed */
export async function publishCreation(id: string, orgId: string): Promise<FlowCreation> {
  const res = await fetch(`${BASE}/creations/${id}/publish`, {
    method: "POST",
    headers: headers(orgId),
  });
  return handleResponse<FlowCreation>(res);
}

/** Unpublish */
export async function unpublishCreation(id: string, orgId: string): Promise<FlowCreation> {
  const res = await fetch(`${BASE}/creations/${id}/unpublish`, {
    method: "POST",
    headers: headers(orgId),
  });
  return handleResponse<FlowCreation>(res);
}

/** Clone into caller's org */
export async function cloneCreation(id: string, orgId: string): Promise<FlowCreation> {
  const res = await fetch(`${BASE}/creations/${id}/clone`, {
    method: "POST",
    headers: headers(orgId),
  });
  return handleResponse<FlowCreation>(res);
}
