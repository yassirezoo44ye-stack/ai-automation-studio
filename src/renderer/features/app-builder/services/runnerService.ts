/**
 * Runner service — wraps POST /api/projects/{id}/run/stream and the
 * companion stop / status endpoints.
 *
 * SSE event types emitted by the backend (verified from runner.py +
 * driver implementations — no assumptions):
 *
 *   status       {type, message, project_type?, entry_point?, run_strategy?}
 *   log          {type, stream:"stdout"|"stderr", line:str, ts:number}
 *   html         {type, html_content:str, entry_file:str, project_type:str, message:str}
 *   server_ready {type, preview_url:str, port:number, project_type:str, message:str, command:str}
 *   done         {type, exit_code:number, duration:number, stdout:str, stderr:str,
 *                  project_type:str, command:str, success:bool}
 *   error        {type, category:str, message:str, fix:str[], severity:str, recoverable:bool}
 *   unsupported  {type, category:"unsupported", message:str, fix:str[],
 *                  local_run_hint:str, available_runtimes:str[]}
 *   heartbeat    {type, message:"still running"}
 *
 * No fake data. Every field mirrors the actual backend payload.
 */
import { apiFetch } from "../../../shared/utils/api";

/* ── Run event types ────────────────────────────────────────────────────── */

export type RunEventStatus = {
  type: "status";
  message: string;
  project_type?: string;
  entry_point?: string;
  run_strategy?: string;
};

export type RunEventLog = {
  type: "log";
  stream: "stdout" | "stderr";
  line: string;
  ts: number;
};

export type RunEventHtml = {
  type: "html";
  html_content: string;
  entry_file: string;
  project_type: string;
  message: string;
};

export type RunEventServerReady = {
  type: "server_ready";
  preview_url: string;
  port: number;
  project_type: string;
  message: string;
  command: string;
};

export type RunEventDone = {
  type: "done";
  exit_code: number;
  duration: number;
  stdout: string;
  stderr: string;
  project_type: string;
  command: string;
  success: boolean;
};

export type RunEventError = {
  type: "error";
  category: string;
  message: string;
  fix: string[];
  severity: "low" | "medium" | "high";
  recoverable: boolean;
};

export type RunEventUnsupported = {
  type: "unsupported";
  category: "unsupported";
  message: string;
  fix: string[];
  local_run_hint?: string;
  available_runtimes?: string[];
};

export type RunEventHeartbeat = {
  type: "heartbeat";
  message: string;
};

export type RunEvent =
  | RunEventStatus
  | RunEventLog
  | RunEventHtml
  | RunEventServerReady
  | RunEventDone
  | RunEventError
  | RunEventUnsupported
  | RunEventHeartbeat;

/* ── Process status (GET /api/projects/{id}/process) ────────────────────── */

export type ProcessStatus =
  | { running: true; port: number; project_type: string; command: string; preview_url: string; idle_seconds: number }
  | { running: false };

/* ── Public API ──────────────────────────────────────────────────────────── */

/**
 * Stream runtime events from the backend.
 *
 * Yields typed RunEvent objects. Caller should abort via AbortSignal when
 * the component unmounts or the user clicks Stop.
 *
 * Note: `html` and `server_ready` indicate preview is ready. The caller
 * should stop consuming the stream after either of these (server is now
 * running; further events arrive via the proxy, not via this SSE stream).
 */
export async function* streamRun(
  projectId: string,
  signal?: AbortSignal,
  commandOverride?: string,
): AsyncGenerator<RunEvent> {
  const res = await apiFetch(`/api/projects/${projectId}/run/stream`, {
    method: "POST",
    body: JSON.stringify({ command: commandOverride ?? null }),
    signal,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json() as Record<string, unknown>;
      detail = String(j.detail ?? j.message ?? detail);
    } catch { /* ignore */ }
    // Surface as a structured error event so callers don't need to branch on
    // thrown exceptions vs SSE error events.
    yield {
      type: "error",
      category: "http",
      message: detail,
      fix: ["Ensure the project has been built first"],
      severity: "high",
      recoverable: true,
    } satisfies RunEventError;
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    yield {
      type: "error",
      category: "network",
      message: "No readable response body from run stream",
      fix: ["Retry the operation"],
      severity: "high",
      recoverable: true,
    } satisfies RunEventError;
    return;
  }

  const dec = new TextDecoder();
  let buf = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });

      // SSE events are separated by double newlines
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const json = line.slice("data:".length).trim();
        if (!json) continue;
        try {
          const event = JSON.parse(json) as RunEvent;
          yield event;
        } catch { /* malformed — skip */ }
      }
    }
  } finally {
    reader.cancel();
  }
}

/**
 * Stop (kill) the running process for a project.
 * Calls DELETE /api/projects/{id}/process.
 * Best-effort — does not throw on failure.
 */
export async function stopProject(projectId: string): Promise<void> {
  try {
    await apiFetch(`/api/projects/${projectId}/process`, { method: "DELETE" });
  } catch { /* best effort */ }
}

/**
 * Get the current process status for a project.
 * Calls GET /api/projects/{id}/process.
 */
export async function getProcessStatus(projectId: string): Promise<ProcessStatus> {
  const res = await apiFetch(`/api/projects/${projectId}/process`);
  if (!res.ok) return { running: false };
  return res.json() as Promise<ProcessStatus>;
}
