/**
 * Builder service — wraps the streaming build API.
 *
 * The backend endpoint is POST /api/build/stream, which emits SSE in the form:
 *   data: {"type": "status"|"heartbeat"|"file"|"done"|"error", ...}\n\n
 *
 * This module provides:
 *  - createProjectAndBuild(): creates a project then streams the build
 *  - parseBuildSSE(): reads a ReadableStream of bytes into typed BuildEvent
 *
 * No fake data, no setTimeout simulation, no placeholder percentages.
 */
import { apiFetch, parseJSON, APIError } from "../../../shared/utils/api";
import type { Project } from "../../../shared/types";

/* ── Types ─────────────────────────────────────────────────────── */
export type BuildEventStatus    = { type: "status";    message: string };
export type BuildEventHeartbeat = { type: "heartbeat"; ts: number };
export type BuildEventFile      = { type: "file";      path: string; content: string };
export type BuildEventDone      = { type: "done";      description: string; files: string[]; run_command: string; language: string };
export type BuildEventError     = { type: "error";     message: string };

export type BuildEvent =
  | BuildEventStatus
  | BuildEventHeartbeat
  | BuildEventFile
  | BuildEventDone
  | BuildEventError;

/* ── Project creation ───────────────────────────────────────────── */
export async function createProject(
  name: string, description: string,
): Promise<Project> {
  const r = await apiFetch("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name: name.slice(0, 100), description: description.slice(0, 500) }),
  });
  return parseJSON<Project>(r, "/api/projects");
}

export async function getProject(projectId: string): Promise<Project> {
  const r = await apiFetch(`/api/projects/${projectId}`);
  return parseJSON<Project>(r, `/api/projects/${projectId}`);
}

/* ── Streaming build ────────────────────────────────────────────── */
/**
 * Stream a build for an existing project.
 *
 * Yields typed BuildEvent objects as they arrive from the server.
 * The caller drives the async iterator and can abort via an AbortSignal.
 *
 * Error handling:
 * - Network / HTTP errors throw an APIError.
 * - SSE `error` events yield BuildEventError (caller decides whether to throw).
 * - The server 409s if the project already has an active build — caller must
 *   check before submitting and show an appropriate UI state.
 */
export async function* streamBuild(
  projectId: string,
  prompt: string,
  signal?: AbortSignal,
): AsyncGenerator<BuildEvent> {
  const res = await apiFetch("/api/build/stream", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, prompt }),
    signal,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let detail = `HTTP ${res.status}`;
    try {
      const j = JSON.parse(body);
      detail = j.detail || j.message || detail;
    } catch { /* ignore */ }
    throw new APIError(detail, {
      url: "/api/build/stream",
      status: res.status,
      contentType: res.headers.get("content-type") ?? "",
    });
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No readable body from build stream");

  const decoder = new TextDecoder();
  let buf = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // SSE is delimited by double newlines
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? ""; // last part may be incomplete
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const json = line.slice("data:".length).trim();
        if (!json) continue;
        try {
          const event = JSON.parse(json) as BuildEvent;
          yield event;
        } catch { /* malformed — skip */ }
      }
    }
  } finally {
    reader.cancel();
  }
}

/* ── Derive a project name from a free-form prompt ─────────────── */
export function promptToProjectName(prompt: string): string {
  // Strip leading "build a/an" verbs, take first ~40 chars, capitalise
  const clean = prompt
    .trim()
    .replace(/^(build|create|make|develop)\s+(a|an|the)?\s*/i, "")
    .split(/[.!?\n]/)[0]
    .slice(0, 45)
    .trim();
  return clean.charAt(0).toUpperCase() + clean.slice(1) || "New App";
}
