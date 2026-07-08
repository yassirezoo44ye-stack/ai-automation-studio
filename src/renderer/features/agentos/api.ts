/**
 * AgentOS API client — typed wrappers for /api/agentos/* endpoints.
 */

const BASE = (import.meta.env.VITE_API_URL ?? "") + "/api/agentos";

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("access_token") ?? "";
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const res = await fetch(url.toString(), { headers: authHeaders() });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface AgentResult {
  agent      : string;
  success    : boolean;
  output     : string;
  data       : Record<string, unknown>;
  error?     : string;
  duration_ms: number;
}

export interface AgentStats {
  name        : string;
  call_count  : number;
  success_count: number;
  fail_count  : number;
  avg_ms      : number;
  success_rate: number;
  last_called : number | null;
}

export interface AgentInfo {
  name        : string;
  description : string;
  group       : string;
  hints       : Record<string, unknown>;
  stats       : AgentStats;
}

export interface MemoryRecord {
  agent      : string;
  input      : string;
  args       : string;
  success    : boolean;
  duration_ms: number;
  timestamp  : number;
  error?     : string;
}

export interface SystemStatus {
  agents       : number;
  agent_names  : string[];
  memory_count : number;
  booted       : boolean;
  llm_available: boolean;
  loop_stats   : {
    running         : boolean;
    tick_count      : number;
    interval_s      : number;
    evolution_cycles: number;
    last_tick       : unknown;
  };
  reflections : unknown[];
  suggestions : Suggestion[];
  performance : AgentStats[];
}

export interface Suggestion {
  index      : number;
  title      : string;
  description: string;
  agent_name : string;
  file       : string;
  priority   : number;
  implemented: boolean;
}

export interface DeliberationBid {
  agent     : string;
  score     : number;
  relevance : number;
  confidence: number;
  reasoning : string;
}

export interface DeliberateResult {
  result      : AgentResult;
  deliberation: {
    winner      : string;
    winner_score: number;
    consensus   : number;
    method      : string;
    bids        : DeliberationBid[];
  };
}

// ── API calls ────────────────────────────────────────────────────────────────

export const agentOsApi = {
  run: (input: string, workspace?: string) =>
    post<AgentResult>("/run", { input, workspace }),

  collaborate: (tasks: string[], parallel = false) =>
    post<{ tasks: string[]; results: AgentResult[]; success: boolean }>(
      "/collaborate", { tasks, parallel }
    ),

  plan: (goal: string) =>
    post<{ plan: string[]; results: AgentResult[]; success: boolean }>(
      "/plan", { goal }
    ),

  deliberate: (input: string) =>
    post<DeliberateResult>("/deliberate", { input }),

  status: () => get<SystemStatus>("/status"),

  agents: () => get<{ count: number; agents: AgentInfo[] }>("/agents"),

  memory: (n = 50) => get<{ count: number; records: MemoryRecord[] }>("/memory", { n: String(n) }),

  performance: () => get<{
    total_executions      : number;
    global_error_rate     : number;
    underperforming_agents: string[];
    agent_stats           : AgentStats[];
  }>("/performance"),

  evolve: (dry_run = false) => post<Record<string, unknown>>("/evolve", { dry_run }),

  generate: (description: string, agent_name?: string) =>
    post<{ status: string; agent_name?: string; file?: string; error?: string }>(
      "/generate", { description, agent_name }
    ),

  suggest: (n = 3) =>
    post<{ count: number; suggestions: Suggestion[] }>("/suggest", { n }),

  implement: (index: number) =>
    post<Record<string, unknown>>("/implement", { index }),

  loop: (cycles = 3) =>
    post<{ cycles: number; results: unknown[] }>("/loop", { cycles }),

  loopStats: () => get<Record<string, unknown>>("/loop/stats"),

  reflections: () => get<{ reflections: unknown[] }>("/reflections"),
};
