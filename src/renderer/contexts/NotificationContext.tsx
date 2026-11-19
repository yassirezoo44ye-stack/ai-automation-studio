/**
 * NotificationProvider — fetches the initial page + unread count over REST,
 * then stays live via WS /ws/notifications (reconnects with backoff and
 * backfills on reconnect so nothing is lost while offline). Actions
 * (read/archive/delete/preferences) go through REST — the socket is
 * receive-only, so there's no outgoing queue to manage while offline.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import { useAuth } from "./AuthContext";
import { apiJSON, apiFetch, API } from "../shared/utils/api";
import {
  NotificationContext,
  type Notification, type NotificationCategory, type NotificationFilters,
  type ConnectionStatus,
} from "./notifications";

const PAGE_SIZE = 30;
const MAX_BACKOFF_MS = 30_000;
const HEARTBEAT_INTERVAL_MS = 15_000;

function wsUrl(ticket: string): string {
  const base = API || window.location.origin;
  const url = new URL(base.startsWith("http") ? base : window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/notifications";
  url.search = `?ticket=${encodeURIComponent(ticket)}`;
  return url.toString();
}

async function fetchWsTicket(): Promise<string | null> {
  try {
    const res = await apiFetch("/api/ws/ticket", { method: "POST" });
    if (!res.ok) return null;
    const data = await res.json() as { ticket?: string };
    return data.ticket ?? null;
  } catch {
    return null;
  }
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { user, accessToken } = useAuth();
  const { t } = useTranslation("common");
  const pendingMutations = useRef(new Set<string>());
  const preferencesQueue = useRef(Promise.resolve());
  const confirmedPreferences = useRef<NotificationCategory[]>([]);
  const preferencesRevision = useRef(0);
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const [savingPreferences, setSavingPreferences] = useState(false);

  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("offline");
  const [mutedCategories, setMutedCategories] = useState<NotificationCategory[]>([]);
  const [presenceDeltas, setPresenceDeltas] = useState<Map<string, boolean>>(new Map());
  const [filters, setFiltersState] = useState<NotificationFilters>({
    unreadOnly: false, category: null, search: "",
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestIdRef = useRef(0);
  const currentUserRef = useRef(user?.id);
  useEffect(() => {
    const owner = user?.id;
    const requests = requestIdRef;
    currentUserRef.current = owner;
    void Promise.resolve().then(() => {
      if (currentUserRef.current !== owner) return;
      setNotifications([]); setUnreadCount(0); setStatus("loading");
      setMutedCategories([]); setPreferencesLoaded(false);
      setSavingPreferences(false);
      preferencesRevision.current++;
      confirmedPreferences.current = [];
    });
    return () => { currentUserRef.current = undefined; requests.current++; };
  }, [user?.id]);
  const seenIdsRef = useRef<Set<string>>(new Set());
  // Lets the WS effect (keyed only on user id / token, not on filters) always
  // backfill against the CURRENT filters on reconnect, not whatever was
  // active when the socket was first opened.
  const filtersRef = useRef(filters);
  useEffect(() => { filtersRef.current = filters; }, [filters]);

  const buildQuery = useCallback((f: NotificationFilters, before?: string) => {
    const params = new URLSearchParams();
    if (f.unreadOnly) params.set("unread_only", "true");
    if (f.category) params.set("category", f.category);
    if (f.search.trim()) params.set("search", f.search.trim());
    if (before) params.set("before", before);
    params.set("limit", String(PAGE_SIZE));
    return params.toString();
  }, []);

  const fetchFirstPage = useCallback(async (f: NotificationFilters) => {
    const requestId = ++requestIdRef.current;
    setStatus(prev => (prev === "success" ? "success" : "loading"));
    setError(null);
    try {
      const [list, count] = await Promise.all([
        apiJSON<{ notifications: Notification[]; has_more: boolean }>(
          `/api/notifications?${buildQuery(f)}`,
        ),
        apiJSON<{ unread_count: number }>("/api/notifications/unread-count"),
      ]);
      if (requestIdRef.current !== requestId) return;
      seenIdsRef.current = new Set(list.notifications.map(n => n.id));
      setNotifications(list.notifications);
      setHasMore(list.has_more);
      setUnreadCount(count.unread_count);
      setStatus("success");
    } catch (err) {
      if (requestIdRef.current !== requestId) return;
      setError(err instanceof Error ? err.message : "Failed to load notifications.");
      setStatus("error");
    }
  }, [buildQuery]);

  const fetchPreferences = useCallback(async () => {
    const owner = user?.id;
    const revision = preferencesRevision.current;
    if (!owner || currentUserRef.current !== owner) return;
    try {
      const res = await apiJSON<{ muted_categories: NotificationCategory[] }>("/api/notifications/preferences");
      if (currentUserRef.current !== owner || preferencesRevision.current !== revision) return;
      confirmedPreferences.current = res.muted_categories;
      setMutedCategories(res.muted_categories);
      setPreferencesLoaded(true);
    } catch {
      if (currentUserRef.current === owner && preferencesRevision.current === revision) setError(t("notifications.preferencesFailed"));
    }
  }, [t, user?.id]);

  const refetch = useCallback(() => { void fetchFirstPage(filters); void fetchPreferences(); }, [fetchFirstPage, filters, fetchPreferences]);

  const loadMore = useCallback(() => {
    if (loadingMore || !hasMore || notifications.length === 0) return;
    setLoadingMore(true);
    const requestId = requestIdRef.current;
    const before = notifications[notifications.length - 1].id;
    void apiJSON<{ notifications: Notification[]; has_more: boolean }>(
      `/api/notifications?${buildQuery(filters, before)}`,
    ).then(res => {
      if (requestIdRef.current !== requestId) return;
      setNotifications(prev => {
        const fresh = res.notifications.filter(n => !seenIdsRef.current.has(n.id));
        fresh.forEach(n => seenIdsRef.current.add(n.id));
        return [...prev, ...fresh];
      });
      setHasMore(res.has_more);
    }).catch(() => {
      if (requestIdRef.current === requestId) setError(t("notifications.actionFailed"));
    }).finally(() => setLoadingMore(false));
  }, [loadingMore, hasMore, notifications, buildQuery, filters, t]);

  // Refetch whenever filters change (fresh first page under the new filter).
  useEffect(() => {
    if (!user) return;
    void Promise.resolve().then(() => fetchFirstPage(filters));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, filters]);

  useEffect(() => {
    if (!user?.id) return;
    void Promise.resolve().then(fetchPreferences);
  }, [user?.id, fetchPreferences]);

  // ── WS live stream ─────────────────────────────────────────────────────────

  useEffect(() => {
    if (!user || !accessToken) {
      wsRef.current?.close();
      void Promise.resolve().then(() => setConnectionStatus("offline"));
      return;
    }

    let cancelled = false;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;

    async function connect() {
      if (cancelled) return;
      setConnectionStatus(prev => (prev === "live" ? prev : "connecting"));

      const ticket = await fetchWsTicket();

      if (cancelled) return;

      if (!ticket) {
        // Ticket acquisition failed — backoff and retry; no JWT fallback.
        setConnectionStatus("reconnecting");
        const attempt = ++reconnectAttemptRef.current;
        const delay = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
        reconnectTimerRef.current = setTimeout(() => { void connect(); }, delay);
        return;
      }

      const ws = new WebSocket(wsUrl(ticket));
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptRef.current = 0;
        setConnectionStatus("live");
        // Backfill anything published while we were disconnected/offline.
        void Promise.resolve().then(() => fetchFirstPage(filtersRef.current));
        // Presence heartbeat — each ping refreshes this user's online TTL
        // server-side (see app/core/presence/service.py); piggybacks on the
        // same socket rather than opening a second connection.
        heartbeatTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
        }, HEARTBEAT_INTERVAL_MS);
      };

      ws.onmessage = (evt) => {
        try {
          const frame = JSON.parse(evt.data as string) as { type: string; topic?: string; data?: unknown };
          if (frame.type !== "event" || !frame.data) return;

          if (frame.topic?.startsWith("presence:")) {
            const { user_id: presenceUserId, online } = frame.data as { user_id: string; online: boolean };
            setPresenceDeltas(prev => new Map(prev).set(presenceUserId, online));
            return;
          }

          const incoming = frame.data as Notification;
          if (seenIdsRef.current.has(incoming.id)) return;
          seenIdsRef.current.add(incoming.id);
          setNotifications(prev => [incoming, ...prev]);
          if (!incoming.read_status) setUnreadCount(c => c + 1);
        } catch {
          // Ignore malformed frames (e.g. ping/pong control frames without a data payload).
        }
      };

      ws.onclose = () => {
        if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
        if (cancelled) return;
        setConnectionStatus("reconnecting");
        const attempt = ++reconnectAttemptRef.current;
        const delay = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
        reconnectTimerRef.current = setTimeout(() => { void connect(); }, delay);
      };

      ws.onerror = () => { ws.close(); };
    }

    void connect();
    return () => {
      cancelled = true;
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
    // Keyed on user?.id (a stable primitive), not the `user` object itself —
    // AuthContext's user is normally referentially stable across renders,
    // but depending on the object would reconnect the socket on any render
    // that happens to produce a new (structurally-equal) user reference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, accessToken]);

  const setFilters = useCallback((f: Partial<NotificationFilters>) => {
    setFiltersState(prev => ({ ...prev, ...f }));
  }, []);

  const mutate = useCallback((key: string, action: () => Promise<unknown>, success: () => void) => {
    const owner = user?.id;
    const mutationKey = `${owner}:${key}`;
    if (!owner || currentUserRef.current !== owner || pendingMutations.current.has(mutationKey)) return;
    pendingMutations.current.add(mutationKey);
    setError(null);
    void action().then(() => {
      if (currentUserRef.current === owner) { requestIdRef.current++; success(); }
    })
      .catch(() => { if (currentUserRef.current === owner) setError(t("notifications.actionFailed")); })
      .finally(() => pendingMutations.current.delete(mutationKey));
  }, [t, user?.id]);

  const markRead = useCallback((id: string) => {
    const target = notifications.find(n => n.id === id);
    if (!target || target.read_status) return;
    mutate(id, () => apiJSON(`/api/notifications/${id}/read`, { method: "POST" }), () => {
      setNotifications(prev => filtersRef.current.unreadOnly
        ? prev.filter(n => n.id !== id)
        : prev.map(n => n.id === id ? { ...n, read_status: true } : n));
      setUnreadCount(c => Math.max(0, c - 1));
    });
  }, [notifications, mutate]);

  const markAllRead = useCallback(() => {
    mutate("read-all", () => apiJSON("/api/notifications/read-all", { method: "POST" }), () => {
      void fetchFirstPage(filtersRef.current);
    });
  }, [mutate, fetchFirstPage]);

  const archive = useCallback((id: string) => {
    const target = notifications.find(n => n.id === id);
    mutate(id, () => apiJSON(`/api/notifications/${id}/archive`, { method: "POST" }), () => {
      setNotifications(prev => prev.filter(n => n.id !== id));
      if (target && !target.read_status) setUnreadCount(c => Math.max(0, c - 1));
    });
  }, [notifications, mutate]);

  const remove = useCallback((id: string) => {
    const target = notifications.find(n => n.id === id);
    mutate(id, async () => {
      const res = await apiFetch(`/api/notifications/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Notification deletion rejected");
    }, () => {
      setNotifications(prev => prev.filter(n => n.id !== id));
      if (target && !target.read_status) setUnreadCount(c => Math.max(0, c - 1));
    });
  }, [notifications, mutate]);

  const setMuted = useCallback((category: NotificationCategory, muted: boolean) => {
    // Serialize changes against the last server-confirmed preferences. React
    // state updaters must not send requests (StrictMode can invoke them twice).
    const owner = user?.id;
    preferencesRevision.current++;
    preferencesQueue.current = preferencesQueue.current.then(async () => {
      if (!preferencesLoaded || !owner || currentUserRef.current !== owner) return;
      setSavingPreferences(true);
      setError(null);
      const previous = confirmedPreferences.current;
      const next = muted ? [...new Set([...previous, category])] : previous.filter(c => c !== category);
      try {
        const res = await apiJSON<{ muted_categories: NotificationCategory[] }>("/api/notifications/preferences", {
          method: "PUT", body: JSON.stringify({ muted_categories: next }),
        });
        if (currentUserRef.current !== owner) return;
        preferencesRevision.current++;
        confirmedPreferences.current = res.muted_categories;
        setMutedCategories(res.muted_categories);
      } catch { if (currentUserRef.current === owner) setError(t("notifications.preferencesFailed")); }
      finally { if (currentUserRef.current === owner) setSavingPreferences(false); }
    });
  }, [preferencesLoaded, t, user?.id]);

  const value = useMemo(() => ({
    notifications, unreadCount, status, error, hasMore, loadingMore, connectionStatus,
    filters, setFilters, mutedCategories, refetch, loadMore, markRead, markAllRead,
    archive, remove, setMuted, presenceDeltas, preferencesLoaded, savingPreferences,
  }), [
    notifications, unreadCount, status, error, hasMore, loadingMore, connectionStatus,
    filters, setFilters, mutedCategories, refetch, loadMore, markRead, markAllRead,
    archive, remove, setMuted, presenceDeltas, preferencesLoaded, savingPreferences,
  ]);

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  );
}
