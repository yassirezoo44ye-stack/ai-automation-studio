/**
 * Business Lab API service.
 * Wraps all /api/business/* endpoints.
 */

const API = "/api/business";

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("auth_token") ?? "";
  return { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: authHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(msg || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}

export interface Plan {
  id: string;
  title: string;
  idea_raw: string;
  industry: string | null;
  stage: string;
  status: string;
  readiness_score: number | null;
  workflow_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Section {
  id: string;
  plan_id: string;
  section_key: string;
  title: string;
  content: string;
  status: string;
  agent_name: string | null;
  model_used: string | null;
  tokens_used: number;
  elapsed_ms: number | null;
  retry_count: number;
  error_msg: string | null;
  updated_at: string;
}

export interface Fact {
  id: string;
  plan_id: string;
  fact_key: string;
  value: unknown;
  source_type: string;
  source_url: string | null;
  source_note: string | null;
  status: string;
  confidence: number;
  section: string | null;
  created_by: string | null;
  created_at: string;
}

export interface Competitor {
  id: string;
  plan_id: string;
  name: string;
  website: string | null;
  description: string | null;
  strengths: string[];
  weaknesses: string[];
  pricing: string | null;
  market_position: string | null;
  source_url: string | null;
  verified: boolean;
}

export interface Score {
  overall_score: number;
  breakdown: Record<string, number>;
  evidence_count: number;
  assumption_count: number;
  missing_count: number;
  computed_at: string;
}

export interface PlanDetail {
  plan: Plan;
  sections: Section[];
  facts: Fact[];
  competitors: Competitor[];
  score: Score | null;
}

export const businessService = {
  createPlan: (body: { idea_raw: string; industry?: string; stage?: string }) =>
    req<Plan>("POST", "/plans", body),

  listPlans: () =>
    req<Plan[]>("GET", "/plans"),

  getPlan: (id: string) =>
    req<PlanDetail>("GET", `/plans/${id}`),

  retrySections: (id: string, section_keys: string[]) =>
    req<{ message: string }>("POST", `/plans/${id}/retry`, { section_keys }),

  cancelPlan: (id: string) =>
    req<{ message: string }>("POST", `/plans/${id}/cancel`),

  recomputeScore: (id: string) =>
    req<Score>("POST", `/plans/${id}/score`),

  exportPlan: async (id: string, format_: string, variant: string): Promise<void> => {
    const res = await fetch(`${API}/plans/${id}/export`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ format: format_, variant }),
    });
    if (!res.ok) throw new Error(`Export failed: ${res.status}`);
    const blob = await res.blob();
    const cd   = res.headers.get("content-disposition") ?? "";
    const fn   = cd.match(/filename="([^"]+)"/)?.[1] ?? "business-plan.md";
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url; a.download = fn; a.click();
    URL.revokeObjectURL(url);
  },

  deletePlan: (id: string) =>
    req<void>("DELETE", `/plans/${id}`),

  streamStatus: (id: string, onEvent: (data: unknown) => void): () => void => {
    const token = localStorage.getItem("auth_token") ?? "";
    // EventSource doesn't support custom headers — pass token as query param
    const es = new EventSource(`${API}/plans/${id}/stream?token=${encodeURIComponent(token)}`);
    es.onmessage = (e) => {
      try { onEvent(JSON.parse(e.data)); } catch { /* skip malformed */ }
    };
    es.onerror = () => es.close();
    return () => es.close();
  },
};
