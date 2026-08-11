import type { AccessTokenResponse, ApiErrorBody, MeResponse } from "./types";
import { clearTokenState, getTokenState, setTokenState } from "./tokenStore";

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const API_PREFIX = "/api/v1";
// Must match `Settings.csrf_cookie_name` in backend/app/core/config.py.
const CSRF_COOKIE_NAME = "sp_csrf_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function errorMessage(body: ApiErrorBody | undefined, fallback: string): string {
  if (!body?.detail) return fallback;
  if (typeof body.detail === "string") return body.detail;
  return body.detail.map((e) => e.msg).join("; ") || fallback;
}

/** Reads the CSRF cookie directly from `document.cookie` rather than caching
 * it in JS state — it's set non-httpOnly specifically so this always works,
 * including right after a page reload, when any in-memory cache would be
 * empty but the cookie (and the value the backend expects back) still is not. */
function readCsrfCookie(): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE_NAME}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function applyAuthResult(result: AccessTokenResponse): void {
  setTokenState({ accessToken: result.access_token });
}

async function rawRequest(path: string, init: RequestInit): Promise<Response> {
  return fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
    ...init,
    credentials: "include", // send/receive the httpOnly refresh + csrf cookies
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
}

/** Authenticated request with a single automatic silent-refresh-and-retry on 401. */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  { retryOn401 = true }: { retryOn401?: boolean } = {},
): Promise<T> {
  const { accessToken } = getTokenState();
  const response = await rawRequest(path, {
    ...init,
    headers: {
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...init.headers,
    },
  });

  if (response.status === 401 && retryOn401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return apiFetch<T>(path, init, { retryOn401: false });
    }
  }

  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = await response.json();
    } catch {
      // non-JSON error body — fall through to generic message
    }
    throw new ApiError(response.status, errorMessage(body, `Request failed (${response.status})`));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function register(input: {
  email: string;
  password: string;
  full_name: string;
  organization_name?: string;
}): Promise<AccessTokenResponse> {
  const result = await apiFetch<AccessTokenResponse>(
    "/auth/register",
    { method: "POST", body: JSON.stringify(input) },
    { retryOn401: false },
  );
  applyAuthResult(result);
  return result;
}

export async function login(email: string, password: string): Promise<AccessTokenResponse> {
  const result = await apiFetch<AccessTokenResponse>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
    { retryOn401: false },
  );
  applyAuthResult(result);
  return result;
}

// De-duplicates concurrent callers onto a single in-flight request. Without
// this, two callers racing (React StrictMode's double-effect in dev; two tabs
// silently refreshing on load in prod; a 401-triggered retry overlapping a
// bootstrap refresh) both present the *same* refresh cookie. The backend's
// rotation is atomic by design (see backend/app/services/auth_service.py) —
// exactly one of them "wins" and the other gets a legitimate 401. But that
// loser's failure handler would otherwise call `clearTokenState()` and wipe
// out the access token the winner just successfully applied a moment earlier.
// Sharing one promise means every caller sees the *same* outcome instead.
let inFlightRefresh: Promise<boolean> | null = null;

export function tryRefresh(): Promise<boolean> {
  if (inFlightRefresh) return inFlightRefresh;
  inFlightRefresh = performRefresh().finally(() => {
    inFlightRefresh = null;
  });
  return inFlightRefresh;
}

async function performRefresh(): Promise<boolean> {
  const csrfToken = readCsrfCookie();
  try {
    const response = await rawRequest("/auth/refresh", {
      method: "POST",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
    });
    if (!response.ok) {
      clearTokenState();
      return false;
    }
    const result = (await response.json()) as AccessTokenResponse;
    applyAuthResult(result);
    return true;
  } catch {
    clearTokenState();
    return false;
  }
}

export async function logout(): Promise<void> {
  const csrfToken = readCsrfCookie();
  try {
    await rawRequest("/auth/logout", {
      method: "POST",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
    });
  } finally {
    clearTokenState();
  }
}

export async function fetchMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>("/auth/me");
}
