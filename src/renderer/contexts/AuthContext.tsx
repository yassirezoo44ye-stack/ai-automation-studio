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

const API = import.meta.env.VITE_API_URL ?? "";
const REFRESH_KEY = "axon_refresh_token";

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
  return fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers as Record<string, string> ?? {}),
    },
  });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Ref lets scheduleRefresh call doRefresh without creating a circular dep
  const doRefreshRef = useRef<() => Promise<{ token: string | null; networkError?: string }>>(async () => ({ token: null }));

  const scheduleRefresh = useCallback((delayMs = 13 * 60 * 1000) => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    // Refresh 2 min before expiry (access tokens last 15 min).
    // On network error, retry with exponential backoff capped at 5 min.
    refreshTimerRef.current = setTimeout(async () => {
      const { token, networkError } = await doRefreshRef.current();
      if (token) {
        scheduleRefresh();
      } else if (networkError) {
        const backoff = Math.min(delayMs * 2, 5 * 60 * 1000);
        scheduleRefresh(backoff);
      }
      // If token is null and no networkError, the session was legitimately
      // expired — doRefresh already called logout(); do not reschedule.
    }, delayMs);
  }, []);

  const doRefresh = useCallback(async (): Promise<{ token: string | null; networkError?: string }> => {
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
  }, [scheduleRefresh]);

  // Keep ref in sync so scheduleRefresh always calls the latest version
  // eslint-disable-next-line react-hooks/refs
  doRefreshRef.current = doRefresh;

  const fetchMe = useCallback(async (token: string) => {
    const res = await apiFetch("/api/auth/me", {}, token);
    if (res.status === 401) {
      // Token was revoked server-side — clear the local session.
      localStorage.removeItem(REFRESH_KEY);
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

  // Bootstrap from stored refresh token on mount
  useEffect(() => {
    void (async () => {
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
  }, [doRefresh, fetchMe]);

  const login = useCallback(async (email: string, password: string, remember = false) => {
    const res = await apiFetch("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, remember }),
    });
    if (!res.ok) {
      const err = await parseJSON<{ detail?: string }>(res, "/api/auth/login").catch(() => ({ detail: "Login failed" }));
      throw new Error(err.detail ?? "Login failed");
    }
    const data = await parseJSON<{ access_token: string; refresh_token: string; user: AuthUser }>(res, "/api/auth/login");
    localStorage.setItem(REFRESH_KEY, data.refresh_token);
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
