import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { parseJSON } from "../utils/api";

const API = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
const REFRESH_KEY = "axon_refresh_token";
// The legacy subscription-token system (app/core/auth.py) — sent as
// X-Sub-Token on every request made through shared/utils/api.ts's fetch
// helpers, independently of accessToken/REFRESH_KEY. It has no
// server-side revocation (a bare HMAC-signed, time-limited token), so
// leaving it in localStorage after a logout or a failed/expired refresh
// would let anything still using those helpers keep making authenticated
// requests with a session the user (or the backend) just ended — cleared
// alongside REFRESH_KEY everywhere a session is torn down.
const SUB_TOKEN_KEY = "sub_token";

function setGlobalToken(token: string | null) {
  (window as unknown as Record<string, string | null>).__axon_access_token = token;
}

export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  email_verified: boolean;
  avatar_url: string | null;
  created_at: string | null;
}

interface AuthContextType {
  user: AuthUser | null;
  accessToken: string | null;
  loading: boolean;
  /** Set when bootstrap refresh fails due to a backend/network error (not when simply logged out). */
  bootstrapError: string | null;
  login: (email: string, password: string, remember?: boolean) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<{ message: string }>;
  logout: () => Promise<void>;
  updateProfile: (data: { name?: string; avatar_url?: string }) => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

async function apiFetch(path: string, init?: RequestInit, token?: string): Promise<Response> {
  try {
    return await fetch(`${API}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers as Record<string, string> ?? {}),
      },
    });
  } catch (err) {
    // A rejected fetch() (as opposed to a non-2xx response, which resolves
    // normally) means the request never reached the server — DNS failure,
    // connection refused, mixed HTTP/HTTPS content, or a CORS preflight the
    // backend rejected. The browser's own message ("Failed to fetch") is
    // accurate but gives no next step, so surface the actual URL and the
    // two most common causes for this app's split-deployment setup
    // (Vercel frontend + Render backend) without discarding the original error.
    const detail = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Cannot reach ${API || "(empty VITE_API_URL)"}${path}. Check that VITE_API_URL is set correctly and that the backend's EXTRA_CORS_ORIGINS includes this frontend's origin. (${detail})`,
    );
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Ref lets scheduleRefresh call doRefresh without creating a circular dep
  const doRefreshRef = useRef<() => Promise<{ token: string | null; networkError?: string }>>(async () => ({ token: null }));
  // Ref lets scheduleRefresh call itself (from within its own setTimeout) without a self-referential closure
  const scheduleRefreshRef = useRef<(delayMs?: number) => void>(() => {});
  // Dedupes concurrent doRefresh() calls (StrictMode double-invoking the
  // bootstrap effect, or a scheduled refresh racing a manual one) onto a
  // single in-flight request. Without this, two /api/auth/refresh calls
  // race with the same stored token; the backend rotates it on the first
  // and 401s the second, whose "legitimately expired" handling then clears
  // the session the first call just established.
  const refreshInFlightRef = useRef<Promise<{ token: string | null; networkError?: string }> | null>(null);

  const scheduleRefresh = useCallback((delayMs = 13 * 60 * 1000) => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    // Refresh 2 min before expiry (access tokens last 15 min).
    // On network error, retry with exponential backoff capped at 5 min.
    refreshTimerRef.current = setTimeout(async () => {
      const { token, networkError } = await doRefreshRef.current();
      if (token) {
        scheduleRefreshRef.current();
      } else if (networkError) {
        const backoff = Math.min(delayMs * 2, 5 * 60 * 1000);
        scheduleRefreshRef.current(backoff);
      }
      // If token is null and no networkError, the session was legitimately
      // expired — doRefresh already called logout(); do not reschedule.
    }, delayMs);
  }, []);

  useEffect(() => {
    scheduleRefreshRef.current = scheduleRefresh;
  }, [scheduleRefresh]);

  const doRefresh = useCallback((): Promise<{ token: string | null; networkError?: string }> => {
    if (refreshInFlightRef.current) return refreshInFlightRef.current;

    const run = async (): Promise<{ token: string | null; networkError?: string }> => {
      const stored = localStorage.getItem(REFRESH_KEY);
      if (!stored) return { token: null };
      try {
        const res = await apiFetch("/api/auth/refresh", {
          method: "POST",
          body: JSON.stringify({ refresh_token: stored }),
        });
        if (res.status === 401) {
          // Token is legitimately expired/revoked — clear session, not an error
          localStorage.removeItem(REFRESH_KEY);
          localStorage.removeItem(SUB_TOKEN_KEY);
          setGlobalToken(null);
          setUser(null);
          setAccessToken(null);
          return { token: null };
        }
        if (!res.ok) {
          // 5xx or unexpected — backend problem, keep the stored token for retry
          return { token: null, networkError: `Server error (${res.status}). Please try again.` };
        }
        const data = await parseJSON<{ access_token: string; refresh_token: string }>(res, "/api/auth/refresh");
        localStorage.setItem(REFRESH_KEY, data.refresh_token);
        setGlobalToken(data.access_token);
        setAccessToken(data.access_token);
        scheduleRefresh();
        return { token: data.access_token };
      } catch {
        return { token: null, networkError: "Cannot reach the server. Check your connection." };
      }
    };

    const promise = run().finally(() => { refreshInFlightRef.current = null; });
    refreshInFlightRef.current = promise;
    return promise;
  }, [scheduleRefresh]);

  // Keep ref in sync so scheduleRefresh always calls the latest version
  useEffect(() => {
    doRefreshRef.current = doRefresh;
  }, [doRefresh]);

  const fetchMe = useCallback(async (token: string) => {
    const res = await apiFetch("/api/auth/me", {}, token);
    if (res.status === 401) {
      // Token was revoked server-side — clear the local session.
      localStorage.removeItem(REFRESH_KEY);
      localStorage.removeItem(SUB_TOKEN_KEY);
      setGlobalToken(null);
      setUser(null);
      setAccessToken(null);
      return;
    }
    if (!res.ok) {
      // 5xx or transient error — keep existing user state, do not log out.
      console.warn("[auth] /api/auth/me returned", res.status, "— keeping session");
      return;
    }
    const u = await parseJSON<AuthUser>(res, "/api/auth/me");
    setUser(u);
  }, []);

  // Bootstrap from stored refresh token on mount (+ handle OAuth callback)
  useEffect(() => {
    void (async () => {
      // OAuth callback: /oauth-callback?code=<one-time exchange code>
      // (tokens themselves never appear in the URL — redeemed server-side
      // below via POST /api/auth/oauth-exchange, see app/routers/auth_users.py)
      if (window.location.pathname === "/oauth-callback") {
        const params = new URLSearchParams(window.location.search);
        const code = params.get("code");
        if (code) {
          try {
            const res = await apiFetch("/api/auth/oauth-exchange", {
              method: "POST",
              body: JSON.stringify({ code }),
            });
            const data = await parseJSON<{ access_token: string; refresh_token: string; sub_token?: string }>(
              res, "/api/auth/oauth-exchange",
            );
            localStorage.setItem(REFRESH_KEY, data.refresh_token);
            if (data.sub_token) localStorage.setItem(SUB_TOKEN_KEY, data.sub_token);
            setGlobalToken(data.access_token);
            setAccessToken(data.access_token);
            await fetchMe(data.access_token);
            scheduleRefresh();
          } catch (err) {
            console.warn("[auth] OAuth exchange failed", err);
          }
          // Clean URL without reloading, whether the exchange succeeded or not
          window.history.replaceState({}, "", "/");
          setLoading(false);
          return;
        }
      }

      const stored = localStorage.getItem(REFRESH_KEY);
      if (!stored) { setLoading(false); return; }
      const { token, networkError } = await doRefresh();
      if (networkError) {
        setBootstrapError(networkError);
      } else if (token) {
        await fetchMe(token);
      }
      setLoading(false);
    })();
    return () => { if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current); };
  }, [doRefresh, fetchMe, scheduleRefresh]);

  const login = useCallback(async (email: string, password: string, remember = false) => {
    const res = await apiFetch("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, remember }),
    });
    if (!res.ok) {
      const err = await parseJSON<{ detail?: string }>(res, "/api/auth/login").catch(() => ({ detail: "Login failed" }));
      throw new Error(err.detail ?? "Login failed");
    }
    const data = await parseJSON<{ access_token: string; refresh_token: string; sub_token: string; user: AuthUser }>(res, "/api/auth/login");
    localStorage.setItem(REFRESH_KEY, data.refresh_token);
    if (data.sub_token) localStorage.setItem(SUB_TOKEN_KEY, data.sub_token);
    setGlobalToken(data.access_token);
    setAccessToken(data.access_token);
    setUser(data.user);
    scheduleRefresh();
  }, [scheduleRefresh]);

  const register = useCallback(async (name: string, email: string, password: string) => {
    const res = await apiFetch("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ name, email, password }),
    });
    if (!res.ok) {
      const err = await parseJSON<{ detail?: string }>(res, "/api/auth/register").catch(() => ({ detail: "Registration failed" }));
      throw new Error(err.detail ?? "Registration failed");
    }
    return parseJSON<{ message: string }>(res, "/api/auth/register");
  }, []);

  const logout = useCallback(async () => {
    const stored = localStorage.getItem(REFRESH_KEY);
    if (stored) {
      await apiFetch("/api/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: stored }),
      }).catch(() => {});
    }
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(SUB_TOKEN_KEY);
    setGlobalToken(null);
    setUser(null);
    setAccessToken(null);
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
  }, []);

  const updateProfile = useCallback(async (data: { name?: string; avatar_url?: string }) => {
    if (!accessToken) throw new Error("Not authenticated");
    const res = await apiFetch("/api/auth/me", { method: "PUT", body: JSON.stringify(data) }, accessToken);
    if (!res.ok) {
      const err = await parseJSON<{ detail?: string }>(res, "PUT /api/auth/me").catch(() => ({ detail: "Update failed" }));
      throw new Error(err.detail ?? "Update failed");
    }
    const updated = await parseJSON<AuthUser>(res, "/api/auth/me");
    setUser(updated);
  }, [accessToken]);

  const refreshUser = useCallback(async () => {
    if (!accessToken) return;
    await fetchMe(accessToken);
  }, [accessToken, fetchMe]);

  return (
    <AuthContext.Provider value={{ user, accessToken, loading, bootstrapError, login, register, logout, updateProfile, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}
