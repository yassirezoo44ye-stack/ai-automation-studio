/**
 * useTeamChat — REST history + live WS delivery for one chat room
 * (app/core/chat/, app/routers/team_chat.py, /ws/chat/{room_key}).
 *
 * teamId null = the organization's org-wide "General" room; a team id
 * scopes to that team's own room. Reconnect-with-backoff mirrors
 * NotificationContext's own WS effect — this hook is page-scoped (one
 * room at a time) rather than a global context, since unlike notifications
 * a user isn't subscribed to every room at once.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { apiJSON, API } from "../utils/api";

export interface ChatMessage {
  id: string;
  organization_id: string;
  team_id: string | null;
  user_id: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  email: string;
  name: string | null;
  avatar_url: string | null;
}

export type ChatConnectionStatus = "connecting" | "live" | "reconnecting" | "offline";

const MAX_BACKOFF_MS = 30_000;

function wsUrl(roomKey: string, token: string): string {
  const base = API || window.location.origin;
  const url = new URL(base.startsWith("http") ? base : window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/ws/chat/${roomKey}`;
  url.search = `?token=${encodeURIComponent(token)}`;
  return url.toString();
}

export function useTeamChat(organizationId: string | null, teamId: string | null) {
  const { accessToken } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [connectionStatus, setConnectionStatus] = useState<ChatConnectionStatus>("offline");
  const [sending, setSending] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());

  const restBase = teamId
    ? `/api/orgs/${organizationId}/teams/${teamId}/chat/messages`
    : `/api/orgs/${organizationId}/chat/messages`;
  const roomKey = teamId ? `team:${teamId}` : `org:${organizationId}`;

  const load = useCallback(async () => {
    if (!organizationId) return;
    setStatus(prev => (prev === "success" ? prev : "loading"));
    try {
      const res = await apiJSON<{ messages: ChatMessage[] }>(restBase);
      seenIdsRef.current = new Set(res.messages.map(m => m.id));
      // API returns newest-first (for REST pagination); the panel wants
      // oldest-first so new messages append at the bottom like any chat UI.
      setMessages([...res.messages].reverse());
      setStatus("success");
    } catch {
      setStatus("error");
    }
  }, [restBase, organizationId]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  useEffect(() => {
    if (!organizationId || !accessToken) {
      wsRef.current?.close();
      void Promise.resolve().then(() => setConnectionStatus("offline"));
      return;
    }

    let cancelled = false;

    function connect() {
      if (cancelled) return;
      setConnectionStatus(prev => (prev === "live" ? prev : "connecting"));
      const ws = new WebSocket(wsUrl(roomKey, accessToken as string));
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptRef.current = 0;
        setConnectionStatus("live");
        void Promise.resolve().then(load);
      };

      ws.onmessage = (evt) => {
        try {
          const frame = JSON.parse(evt.data as string) as { type: string; data?: ChatMessage };
          if (frame.type !== "event" || !frame.data) return;
          const incoming = frame.data;
          if (seenIdsRef.current.has(incoming.id)) return;
          seenIdsRef.current.add(incoming.id);
          setMessages(prev => [...prev, incoming]);
        } catch {
          // Ignore malformed frames (ping/pong control frames without a data payload).
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomKey, accessToken, organizationId]);

  const send = useCallback(async (body: string): Promise<boolean> => {
    const trimmed = body.trim();
    if (!trimmed || !organizationId) return false;
    setSending(true);
    try {
      // No optimistic append: the poster is also subscribed to this room's
      // WS topic, so the server's post-persist broadcast delivers the new
      // message back to them the same way it does every other member.
      await apiJSON(restBase, { method: "POST", body: JSON.stringify({ body: trimmed }) });
      return true;
    } catch {
      return false;
    } finally {
      setSending(false);
    }
  }, [restBase, organizationId]);

  return { messages, status, connectionStatus, sending, send, reload: load };
}
