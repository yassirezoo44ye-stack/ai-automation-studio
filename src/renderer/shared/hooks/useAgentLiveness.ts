/**
 * useAgentLiveness — live running/idle status per AgentOS agent, over the
 * existing /ws/system broadcast (see app/agents/liveness.py's bridge from
 * AgentKernel.run()'s "agent.started"/"agent.finished" events).
 *
 * Same snapshot-plus-delta shape as useOrgPresence: this hook only holds
 * deltas received since connecting — GET /api/agentos/agents already
 * returns each agent's current `live.status`, so callers merge that
 * REST-fetched snapshot with `runningDeltas` for a value that's correct
 * from first render onward, not just after the first WS event.
 */
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { API } from "../utils/api";

const MAX_BACKOFF_MS = 30_000;

function wsUrl(token: string): string {
  const base = API || window.location.origin;
  const url = new URL(base.startsWith("http") ? base : window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/system";
  url.search = `?token=${encodeURIComponent(token)}`;
  return url.toString();
}

export function useAgentLiveness() {
  const { accessToken } = useAuth();
  const [runningDeltas, setRunningDeltas] = useState<Map<string, boolean>>(new Map());
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!accessToken) {
      wsRef.current?.close();
      return;
    }

    let cancelled = false;

    function connect() {
      if (cancelled) return;
      const ws = new WebSocket(wsUrl(accessToken as string));
      wsRef.current = ws;

      ws.onopen = () => { reconnectAttemptRef.current = 0; };

      ws.onmessage = (evt) => {
        try {
          const frame = JSON.parse(evt.data as string) as {
            type: string; topic?: string;
            data?: { agent?: string; status?: "running" | "idle" };
          };
          if (frame.type !== "event" || frame.topic !== "system" || !frame.data?.agent) return;
          const { agent, status } = frame.data;
          setRunningDeltas(prev => new Map(prev).set(agent, status === "running"));
        } catch {
          // Ignore malformed frames (ping/pong control frames without a data payload).
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
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
  }, [accessToken]);

  return { runningDeltas };
}
