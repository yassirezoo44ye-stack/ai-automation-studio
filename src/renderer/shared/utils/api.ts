// Trailing slashes are stripped so `${API}/api/...` call sites never
// produce a double slash (e.g. VITE_API_URL="https://host.com/") — a
// double slash is a different path to most routers and 404s.
export const API = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

export function getToken(): string { return localStorage.getItem("sub_token") ?? ""; }

function getJwt(): string {
  return (window as unknown as Record<string, string>).__axon_access_token ?? "";
}

/** Set by OrgContext when the user switches organizations — read by apiFetch/authH. */
function getOrgId(): string {
  return (window as unknown as Record<string, string>).__axon_org_id ?? "";
}

export function authH(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json", "X-Sub-Token": getToken(), ...extra };
  const jwt = getJwt();
  if (jwt) h["Authorization"] = `Bearer ${jwt}`;
  const orgId = getOrgId();
  if (orgId) h["X-Organization-Id"] = orgId;
  return h;
}

/** Set by AuthContext on mount to its deduped doRefresh() — lets this
 * module trigger a silent token refresh without importing React context
 * machinery (same window-global-bridge pattern already used for the
 * access token/org id above). */
type RefreshFn = () => Promise<{ token: string | null; networkError?: string }>;
function getRefreshFn(): RefreshFn | undefined {
  return (window as unknown as Record<string, RefreshFn | undefined>).__axon_refresh_fn;
}

function buildHeaders(path: string, init?: RequestInit): Record<string, string> {
  const jwt = getJwt();
  const orgId = getOrgId();
  return {
    "X-Sub-Token": getToken(),
    ...(jwt ? { "Authorization": `Bearer ${jwt}` } : {}),
    ...(orgId ? { "X-Organization-Id": orgId } : {}),
    ...(init?.body != null ? { "Content-Type": "application/json" } : {}),
    ...(init?.headers as Record<string, string> ?? {}),
  };
}

/**
 * Authenticated fetch — all /api/* calls must use this.
 *
 * On a 401 that the backend has specifically flagged as an expired JWT
 * (`{"error": "token_expired"}`, see app/factory.py's api_auth_middleware),
 * attempts exactly one silent refresh-and-retry before giving up — this is
 * the only place that recovery happens; previously every 401 (expired,
 * invalid, or missing credentials, indistinguishable from the client's
 * side before this fix) just propagated to the caller as a hard failure,
 * with a background 13-minute timer as the sole renewal mechanism (which
 * a backgrounded/throttled tab or a missed tick could outrun). Never
 * retries for /api/auth/* itself, and never loops more than once even if
 * the retried request also comes back 401.
 */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${API}${path}`, { ...init, headers: buildHeaders(path, init) });

  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    let expired = false;
    try {
      expired = (await res.clone().json())?.error === "token_expired";
    } catch {
      // Non-JSON or empty 401 body — not our refreshable shape.
    }
    if (expired) {
      const refresh = getRefreshFn();
      const { token } = (await refresh?.()) ?? { token: null };
      if (token) {
        return fetch(`${API}${path}`, { ...init, headers: buildHeaders(path, init) });
      }
    }
  }

  return res;
}

// ── Structured API error ──────────────────────────────────────────────────────

export class APIError extends Error {
  constructor(
    message: string,
    public readonly details: {
      url: string;
      status: number;
      contentType: string;
      probableCause?: string;
      suggestedFix?: string;
    },
  ) {
    super(message);
    this.name = "APIError";
  }
}

// ── HTML classifier ───────────────────────────────────────────────────────────

function classifyHtml(html: string): string {
  const lc = html.toLowerCase();
  if (lc.includes("__vite") || lc.includes("vite") || (lc.includes("root") && lc.includes("<!doctype"))) {
    return "React SPA index.html — VITE_API_URL is empty or points to the wrong host. The frontend is serving itself instead of the backend.";
  }
  if (lc.includes("502") || lc.includes("bad gateway"))    return "502 Bad Gateway — backend is down or unreachable on Render.";
  if (lc.includes("503") || lc.includes("service unavailable")) return "503 Service Unavailable — backend is starting up or overloaded.";
  if (lc.includes("404") || lc.includes("not found"))      return "404 page — endpoint does not exist on the server.";
  if (lc.includes("login") || lc.includes("sign in") || lc.includes("redirect")) return "Auth redirect — session expired or auth middleware issued a redirect.";
  if (lc.includes("render") || lc.includes("render.com"))  return "Render platform error page — check Render dashboard logs.";
  return "HTML page — server returned HTML instead of JSON.";
}

// ── Safe JSON parser ──────────────────────────────────────────────────────────

/**
 * Parse JSON from a Response with full diagnostics when something goes wrong.
 *
 * Checks response.ok, validates Content-Type, detects HTML error pages, and
 * throws an APIError with endpoint, status, content-type, probable cause, and
 * a suggested fix — so the console message is actionable rather than cryptic.
 *
 * @param res      The fetch Response to parse.
 * @param endpoint Optional label (used in error messages; falls back to res.url).
 */
export async function parseJSON<T>(res: Response, endpoint?: string): Promise<T> {
  const url = endpoint ?? res.url ?? "unknown endpoint";
  const status = res.status;
  const ct = res.headers.get("content-type") ?? "";

  // Read body once — body can only be consumed once, so we always use text first.
  const body = await res.text().catch(() => "");
  const trimmed = body.trimStart();
  const isHtml = ct.includes("text/html") || trimmed.startsWith("<!DOCTYPE") || trimmed.startsWith("<html") || trimmed.startsWith("<!doctype");

  if (!res.ok || isHtml) {
    let probableCause: string;
    let suggestedFix: string;

    if (isHtml) {
      probableCause = classifyHtml(body);
      suggestedFix  = "Set VITE_API_URL to your backend URL (e.g. https://your-api.onrender.com). Never leave it empty in production.";
    } else if (status === 401) {
      probableCause = "Unauthorized — token missing or expired.";
      suggestedFix  = "Log in again or check the sub_token value in localStorage.";
    } else if (status === 403) {
      probableCause = "Forbidden — subscription or permission check failed.";
      suggestedFix  = "Check your subscription status or user permissions.";
    } else if (status === 404) {
      probableCause = `Endpoint not found: ${url}`;
      suggestedFix  = "Verify the route exists in the backend router and the URL is correct.";
    } else if (status >= 500) {
      probableCause = "Internal server error.";
      suggestedFix  = "Check backend logs on the Render dashboard.";
    } else {
      probableCause = `HTTP ${status} error.`;
      suggestedFix  = "Check the request parameters and backend logs.";
    }

    console.error(
      `[API Error]\n` +
      `  Endpoint:       ${url}\n` +
      `  Status:         ${status} ${res.statusText}\n` +
      `  Content-Type:   ${ct || "(none)"}\n` +
      `  Probable cause: ${probableCause}\n` +
      `  Suggested fix:  ${suggestedFix}\n` +
      `  Response (first 500 chars):\n  ${body.slice(0, 500)}`,
    );

    throw new APIError(probableCause, { url, status, contentType: ct, probableCause, suggestedFix });
  }

  // Parse JSON from the text we already read.
  try {
    return JSON.parse(body) as T;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(
      `[API] JSON parse failed\n` +
      `  Endpoint:  ${url}\n` +
      `  Status:    ${status}\n` +
      `  CT:        ${ct}\n` +
      `  Body:      ${body.slice(0, 500)}`,
    );
    throw new APIError(`JSON parse failed at ${url}: ${msg}`, { url, status, contentType: ct });
  }
}

/**
 * Authenticated fetch that immediately parses the JSON response.
 * The single call site for all /api/* JSON requests.
 */
export async function apiJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  return parseJSON<T>(res, `${API}${path}`);
}
