/**
 * Runs service — normalises job-queue and agent-run data into a single Run type.
 *
 * Two backend sources:
 *  • GET /api/jobs          – org-scoped async job queue (requires X-Organization-Id)
 *  • GET /api/agent-runs    – user-scoped DB table (works without org)
 *
 * If the jobs endpoint returns 400/404 (no org context), we fall back to
 * agent-runs only. Duration is always calculated from real timestamps —
 * never fabricated.
 */
import { apiFetch, parseJSON, APIError } from "../../../shared/utils/api";

/* ── Canonical run type ─────────────────────────────────────────── */
export type RunStatus = "running" | "completed" | "failed" | "pending" | "cancelled";

export interface Run {
  id: string;
  kind: string;
  status: RunStatus;
  progress: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  source: "job" | "agent_run";
}

export interface RunStats {
  total: number;
  running: number;
  completed: number;
  failed: number;
  pending: number;
}

/* ── Adapter: job queue response → Run ─────────────────────────── */
interface RawJob {
  id: string;
  kind: string;
  status: string;
  progress: number;
  error: string | null;
  created_at: number; // epoch float
  started_at: number | null;
  finished_at: number | null;
  duration_ms: number | null;
}

function jobToRun(j: RawJob): Run {
  const toIso = (t: number | null) => t ? new Date(t * 1000).toISOString() : null;
  return {
    id: j.id,
    kind: j.kind,
    status: sanitiseStatus(j.status),
    progress: j.progress ?? 0,
    error: j.error ?? null,
    created_at: toIso(j.created_at) ?? new Date().toISOString(),
    started_at: toIso(j.started_at),
    finished_at: toIso(j.finished_at),
    source: "job",
  };
}

/* ── Adapter: agent_runs DB row → Run ──────────────────────────── */
interface RawAgentRun {
  id: string;
  project_id: string;
  agent_type: string;
  status: string;
  started_at: string;
  completed_at: string | null;
}

function agentRunToRun(a: RawAgentRun): Run {
  return {
    id: a.id,
    kind: a.agent_type || "agent_run",
    status: sanitiseStatus(a.status),
    progress: a.completed_at ? 100 : 0,
    error: null,
    created_at: a.started_at,
    started_at: a.started_at,
    finished_at: a.completed_at,
    source: "agent_run",
  };
}

function sanitiseStatus(raw: string): RunStatus {
  const known: RunStatus[] = ["running", "completed", "failed", "pending", "cancelled"];
  const s = (raw ?? "").toLowerCase();
  return known.includes(s as RunStatus) ? (s as RunStatus) : "pending";
}

/* ── Fetch both sources, merge, deduplicate ─────────────────────── */
export async function fetchRuns(opts?: { status?: RunStatus; kind?: string; limit?: number }): Promise<Run[]> {
  const params = new URLSearchParams();
  if (opts?.status)  params.set("status", opts.status);
  if (opts?.kind)    params.set("kind",   opts.kind);
  if (opts?.limit)   params.set("limit",  String(opts.limit));
  const jobsPath = `/api/jobs${params.size ? `?${params}` : ""}`;

  const [jobsResult, agentResult] = await Promise.allSettled([
    apiFetch(jobsPath).then(r => parseJSON<{ jobs: RawJob[] }>(r, jobsPath)),
    apiFetch("/api/agent-runs").then(r => parseJSON<RawAgentRun[]>(r, "/api/agent-runs")),
  ]);

  const jobs: Run[] =
    jobsResult.status === "fulfilled"
      ? (jobsResult.value.jobs ?? []).map(jobToRun)
      : [];

  // Agent runs fallback / supplement — only use when jobs don't cover them
  const agentRuns: Run[] =
    agentResult.status === "fulfilled"
      ? (Array.isArray(agentResult.value) ? agentResult.value : []).map(agentRunToRun)
      : [];

  // Deduplicate by id, prefer job-queue version
  const seen = new Set(jobs.map(j => j.id));
  const merged = [...jobs, ...agentRuns.filter(a => !seen.has(a.id))];

  // Sort by created_at desc (newest first)
  merged.sort((a, b) =>
    new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  return merged;
}

export async function fetchRunStats(): Promise<RunStats> {
  try {
    const r = await apiFetch("/api/jobs/stats");
    if (!r.ok) throw new APIError(`HTTP ${r.status}`, { url: "/api/jobs/stats", status: r.status, contentType: "" });
    const raw = await parseJSON<{
      total: number; active: number; dead: number;
      counts?: Record<string, number>;
    }>(r, "/api/jobs/stats");
    return {
      total: raw.total ?? 0,
      running: raw.active ?? 0,
      completed: raw.counts?.completed ?? 0,
      failed: raw.dead ?? 0,
      pending: raw.counts?.pending ?? 0,
    };
  } catch {
    return { total: 0, running: 0, completed: 0, failed: 0, pending: 0 };
  }
}

export async function fetchRun(id: string): Promise<Run> {
  const r = await apiFetch(`/api/jobs/${id}`);
  const raw = await parseJSON<RawJob>(r, `/api/jobs/${id}`);
  return jobToRun(raw);
}

export async function cancelRun(id: string): Promise<void> {
  const r = await apiFetch(`/api/jobs/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 409) {
    const body = await r.text().catch(() => "");
    throw new APIError(`Cancel failed: ${body.slice(0, 200)}`, {
      url: `/api/jobs/${id}`,
      status: r.status,
      contentType: "",
    });
  }
}
