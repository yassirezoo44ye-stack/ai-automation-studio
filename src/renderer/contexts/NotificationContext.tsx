/**
 * NotificationProvider — fetches the initial page + unread count over REST,
 * then stays live via WS /ws/notifications (reconnects with backoff and
 * backfills on reconnect so nothing is lost while offline). Actions
 * (read/archive/delete/preferences) go through REST — the socket is
 * receive-only, so there's no outgoing queue to manage while offline.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useAuth } from "./AuthContext";
import { apiJSON, API, authH } from "../shared/utils/api";
import {
  NotificationContext,
  type Notification, type NotificationCategory, type NotificationFilters,
  type ConnectionStatus,
} from "./notifications";

const PAGE_SIZE = 30;
const MAX_BACKOFF_MS = 30_000;

function wsUrl(token: string): string {
  const base = API || window.location.origin;
  const url = new URL(base.startsWith("http") ? base : window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/notifications";
  url.search = `?token=${encodeURIComponent(token)}`;
  return url.toString();
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { user, accessToken } = useAuth();

  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("offline");
  const [mutedCategories, setMutedCategories] = useState<NotificationCategory[]>([]);
  const [filters, setFiltersState] = useState<NotificationFilters>({
    unreadOnly: false, category: null, search: "",
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestIdRef = useRef(0);
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

  const refetch = useCallback(() => { void fetchFirstPage(filters); }, [fetchFirstPage, filters]);

  const loadMore = useCallback(() => {
    if (loadingMore || !hasMore || notifications.length === 0) return;
    setLoadingMore(true);
    const before = notifications[notifications.length - 1].id;
    void apiJSON<{ notifications: Notification[]; has_more: boolean }>(
      `/api/notifications?${buildQuery(filters, before)}`,
    ).then(res => {
      setNotifications(prev => {
        const fresh = res.notifications.filter(n => !seenIdsRef.current.has(n.id));
        fresh.forEach(n => seenIdsRef.current.add(n.id));
        return [...prev, ...fresh];
      });
      setHasMore(res.has_more);
    }).catch(() => {
      // Non-fatal — the list simply doesn't grow; the user can retry via loadMore again.
    }).finally(() => setLoadingMore(false));
  }, [loadingMore, hasMore, notifications, buildQuery, filters]);

  // Refetch whenever filters change (fresh first page under the new filter).
  useEffect(() => {
    if (!user) return;
    void Promise.resolve().then(() => fetchFirstPage(filters));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, filters]);

  useEffect(() => {
    if (!user) return;
    void apiJSON<{ muted_categories: NotificationCategory[] }>("/api/notifications/preferences")
      .then(res => setMutedCategories(res.muted_categories))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  // ── WS live stream ─────────────────────────────────────────────────────────

  useEffect(() => {
    if (!user || !accessToken) {
      wsRef.current?.close();
      void Promise.resolve().then(() => setConnectionStatus("offline"));
      return;
    }

    let cancelled = false;

    function connect() {
      if (cancelled) return;
      setConnectionStatus(prev => (prev === "live" ? prev : "connecting"));
      const ws = new WebSocket(wsUrl(accessToken as string));
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptRef.current = 0;
        setConnectionStatus("live");
        // Backfill anything published while we were disconnected/offline.
        void Promise.resolve().then(() => fetchFirstPage(filtersRef.current));
      };

      ws.onmessage = (evt) => {
        try {
          const frame = JSON.parse(evt.data as string) as { type: string; data?: Notification };
          if (frame.type !== "event" || !frame.data) return;
          const incoming = frame.data;
          if (seenIdsRef.current.has(incoming.id)) return;
          seenIdsRef.current.add(incoming.id);
          setNotifications(prev => [incoming, ...prev]);
          if (!incoming.read_status) setUnreadCount(c => c + 1);
        } catch {
          // Ignore malformed frames (e.g. ping/pong control frames without a data payload).
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setConnectionStatus("reconnecting");
        const attempt = ++reconnectAttemptRef.current;
        const delay = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
        reconnectTimerRef.current = setTimeout(connect, delay);
      };

      ws.onerror = () => { ws.close(); };
    }

    connect();
    return () => {
      cancelled = true;
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

  const markRead = useCallback((id: string) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read_status: true } : n));
    setUnreadCount(c => Math.max(0, c - 1));
    void apiJSON(`/api/notifications/${id}/read`, { method: "POST" }).catch(() => {});
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications(prev => prev.map(n => ({ ...n, read_status: true })));
    setUnreadCount(0);
    void apiJSON("/api/notifications/read-all", { method: "POST" }).catch(() => {});
  }, []);

  const archive = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
    setUnreadCount(c => {
      const n = notifications.find(x => x.id === id);
      return n && !n.read_status ? Math.max(0, c - 1) : c;
    });
    void apiJSON(`/api/notifications/${id}/archive`, { method: "POST" }).catch(() => {});
  }, [notifications]);

  const remove = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
    setUnreadCount(c => {
      const n = notifications.find(x => x.id === id);
      return n && !n.read_status ? Math.max(0, c - 1) : c;
    });
    void fetch(`${API}/api/notifications/${id}`, { method: "DELETE", headers: authH() }).catch(() => {});
  }, [notifications]);

  const setMuted = useCallback((category: NotificationCategory, muted: boolean) => {
    setMutedCategories(prev => {
      const next = muted ? [...new Set([...prev, category])] : prev.filter(c => c !== category);
      void apiJSON("/api/notifications/preferences", {
        method: "PUT", body: JSON.stringify({ muted_categories: next }),
      }).catch(() => {});
      return next;
    });
  }, []);

  const value = useMemo(() => ({
    notifications, unreadCount, status, error, hasMore, loadingMore, connectionStatus,
    filters, setFilters, mutedCategories, refetch, loadMore, markRead, markAllRead,
    archive, remove, setMuted,
  }), [
    notifications, unreadCount, status, error, hasMore, loadingMore, connectionStatus,
    filters, setFilters, mutedCategories, refetch, loadMore, markRead, markAllRead,
    archive, remove, setMuted,
  ]);

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  );
}
