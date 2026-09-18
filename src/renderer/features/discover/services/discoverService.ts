import type {
  FlowCreation,
  CreateCreationPayload,
  UpdateCreationPayload,
  CreationFeedResponse,
  CreationType,
} from "../types/creation.types";
import { apiFetch } from "../../../shared/utils/api";

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
  const res = await apiFetch(`/api/discover${qs}`);
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
  const res = await apiFetch(`/api/discover/mine${qs}`, {
    headers: { "X-Organization-Id": orgId },
  });
  return handleResponse<CreationFeedResponse>(res);
}

/** Create a new creation card */
export async function createCreation(
  orgId: string,
  payload: CreateCreationPayload
): Promise<FlowCreation> {
  const res = await apiFetch(`/api/creations`, {
    method: "POST",
    headers: { "X-Organization-Id": orgId },
    body: JSON.stringify(payload),
  });
  return handleResponse<FlowCreation>(res);
}

/** Get one creation */
export async function getCreation(
  id: string,
  orgId?: string
): Promise<FlowCreation> {
  const res = await apiFetch(`/api/creations/${id}`, {
    ...(orgId ? { headers: { "X-Organization-Id": orgId } } : {}),
  });
  return handleResponse<FlowCreation>(res);
}

/** Update metadata */
export async function updateCreation(
  id: string,
  orgId: string,
  payload: UpdateCreationPayload
): Promise<FlowCreation> {
  const res = await apiFetch(`/api/creations/${id}`, {
    method: "PATCH",
    headers: { "X-Organization-Id": orgId },
    body: JSON.stringify(payload),
  });
  return handleResponse<FlowCreation>(res);
}

/** Delete */
export async function deleteCreation(id: string, orgId: string): Promise<void> {
  const res = await apiFetch(`/api/creations/${id}`, {
    method: "DELETE",
    headers: { "X-Organization-Id": orgId },
  });
  return handleResponse<void>(res);
}

/** Publish to public feed */
export async function publishCreation(id: string, orgId: string): Promise<FlowCreation> {
  const res = await apiFetch(`/api/creations/${id}/publish`, {
    method: "POST",
    headers: { "X-Organization-Id": orgId },
  });
  return handleResponse<FlowCreation>(res);
}

/** Unpublish */
export async function unpublishCreation(id: string, orgId: string): Promise<FlowCreation> {
  const res = await apiFetch(`/api/creations/${id}/unpublish`, {
    method: "POST",
    headers: { "X-Organization-Id": orgId },
  });
  return handleResponse<FlowCreation>(res);
}

/** Clone into caller's org */
export async function cloneCreation(id: string, orgId: string): Promise<FlowCreation> {
  const res = await apiFetch(`/api/creations/${id}/clone`, {
    method: "POST",
    headers: { "X-Organization-Id": orgId },
  });
  return handleResponse<FlowCreation>(res);
}
