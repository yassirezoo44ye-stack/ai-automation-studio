/**
 * useAgentRunSteps — live narrated sub-steps for one specific AgentOS run,
 * over the per-run /ws/system/{runId} channel (see app/agents/liveness.py's
 * publish_step, called from AgentContext.step() inside a running agent's
 * execute()). This is the actual "live computer" signal — what the agent
 * is doing right now — distinct from the running/idle dot useAgentLiveness
 * renders on the agent grid.
 *
 * The socket is scoped to one run: it (re)connects whenever `runId`
 * changes, rather than staying open on a shared broadcast channel and
 * filtering by run_id client-side. Server-side topic isolation is the
 * actual security boundary here — a step frame's payload can carry the
 * run's input text, search queries, or URLs, so it should never reach a
 * connection that isn't subscribed to that run in the first place. The
 * run_id check in onmessage below is just a belt-and-suspenders sanity
 * check, not the thing doing the real work.
 */
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { API } from "../utils/api";

export interface AgentStepFrame {
  run_id: string;
  agent : string;
  step  : string;
  kind  : string;
  [key: string]: unknown;
}

const MAX_BACKOFF_MS = 30_000;

function wsUrl(token: string, runId: string): string {
  const base = API || window.location.origin;
  const url = new URL(base.startsWith("http") ? base : window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/ws/system/${encodeURIComponent(runId)}`;
  url.search = `?token=${encodeURIComponent(token)}`;
  return url.toString();
}

export function useAgentRunSteps(runId: string | null) {
  const { accessToken } = useAuth();
  const [steps, setSteps] = useState<AgentStepFrame[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset during render (not in an effect) when runId changes, per React's
  // "adjusting state when a prop changes" pattern — avoids the cascading
  // render an effect-body setState would trigger.
  const [prevRunId, setPrevRunId] = useState(runId);
  if (runId !== prevRunId) {
    setPrevRunId(runId);
    setSteps([]);
  }

  useEffect(() => {
    if (!accessToken || !runId) {
      wsRef.current?.close();
      return;
    }

    let cancelled = false;
    const topic = `system:${runId}`;

    function connect() {
      if (cancelled) return;
      const ws = new WebSocket(wsUrl(accessToken as string, runId as string));
      wsRef.current = ws;

      ws.onopen = () => { reconnectAttemptRef.current = 0; };

      ws.onmessage = (evt) => {
        try {
          const frame = JSON.parse(evt.data as string) as {
            type: string; topic?: string; data?: Partial<AgentStepFrame>;
          };
          if (frame.type !== "event" || frame.topic !== topic) return;
          const data = frame.data;
          // Distinguish a step frame (has "step") from other control frames.
          if (!data?.step || !data.run_id) return;
          if (data.run_id !== runId) return;
          setSteps(prev => [...prev, data as AgentStepFrame]);
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
  }, [accessToken, runId]);

  return { steps };
}
