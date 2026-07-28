/**
 * useAgentRunSteps — live narrated sub-steps for one specific AgentOS run,
 * over the same /ws/system broadcast useAgentLiveness uses (see
 * app/agents/liveness.py's publish_step, called from AgentContext.step()
 * inside a running agent's execute()). This is the actual "live computer"
 * signal — what the agent is doing right now — distinct from the
 * running/idle dot useAgentLiveness renders on the agent grid.
 *
 * The socket stays open across runs (reconnect-with-backoff, mounted
 * once); which run's steps to keep is controlled by the `runId` argument
 * and filtered client-side via a ref, not by reconnecting — reconnecting
 * on every run would risk missing a run's first steps while the socket
 * re-handshakes.
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

function wsUrl(token: string): string {
  const base = API || window.location.origin;
  const url = new URL(base.startsWith("http") ? base : window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/system";
  url.search = `?token=${encodeURIComponent(token)}`;
  return url.toString();
}

export function useAgentRunSteps(runId: string | null) {
  const { accessToken } = useAuth();
  const [steps, setSteps] = useState<AgentStepFrame[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runIdRef = useRef(runId);

  // Reset during render (not in an effect) when runId changes, per React's
  // "adjusting state when a prop changes" pattern — avoids the cascading
  // render an effect-body setState would trigger.
  const [prevRunId, setPrevRunId] = useState(runId);
  if (runId !== prevRunId) {
    setPrevRunId(runId);
    setSteps([]);
  }

  useEffect(() => {
    runIdRef.current = runId;
  }, [runId]);

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
            type: string; topic?: string; data?: Partial<AgentStepFrame>;
          };
          if (frame.type !== "event" || frame.topic !== "system") return;
          const data = frame.data;
          // Distinguish a step frame (has "step") from a liveness frame
          // (has "status") — both flow over the same topic.
          if (!data?.step || !data.run_id) return;
          if (!runIdRef.current || data.run_id !== runIdRef.current) return;
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
  }, [accessToken]);

  return { steps };
}
