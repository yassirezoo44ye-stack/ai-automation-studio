/**
 * App Builder API client.
 *
 * All calls go through apiFetch/apiJSON so JWT + org headers are sent
 * automatically (matching the rest of the codebase).
 */
import { apiJSON } from "../../shared/utils/api";
import type { AppSpec, BuildResult, AppRecord, AppDetail } from "./types";

const BASE = "/api/app-builder";

export interface PreviewSpecResponse {
  spec: AppSpec;
}

export interface CreateAppResponse {
  spec: AppSpec;
  result: BuildResult;
}

export interface ListAppsResponse {
  apps: AppRecord[];
}

export interface ModifyAppResponse {
  result: BuildResult;
}

/** Generate spec without building — dry run. */
export async function previewSpec(
  prompt: string,
  includeAutomation = false,
): Promise<PreviewSpecResponse> {
  return apiJSON<PreviewSpecResponse>(`${BASE}/preview-spec`, {
    method: "POST",
    body: JSON.stringify({ prompt, include_automation: includeAutomation }),
  });
}

/** Generate spec + build the full application. */
export async function createApp(
  prompt: string,
  includeAutomation = false,
): Promise<CreateAppResponse> {
  return apiJSON<CreateAppResponse>(`${BASE}/apps`, {
    method: "POST",
    body: JSON.stringify({ prompt, include_automation: includeAutomation }),
  });
}

/** List apps in the current org. */
export async function listApps(): Promise<ListAppsResponse> {
  return apiJSON<ListAppsResponse>(`${BASE}/apps`);
}

/** Get app details including spec and version history. */
export async function getApp(appId: string): Promise<AppDetail> {
  return apiJSON<AppDetail>(`${BASE}/apps/${appId}`);
}

/** Incrementally modify an existing app. */
export async function modifyApp(
  appId: string,
  prompt: string,
): Promise<ModifyAppResponse> {
  return apiJSON<ModifyAppResponse>(`${BASE}/apps/${appId}/modify`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

/** Soft-delete an app (admin/owner only). */
export async function deleteApp(appId: string): Promise<void> {
  await apiJSON<{ status: string }>(`${BASE}/apps/${appId}`, {
    method: "DELETE",
  });
}
