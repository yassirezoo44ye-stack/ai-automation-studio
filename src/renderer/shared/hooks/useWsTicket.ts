/**
 * useWsTicket — obtains a short-lived single-use WebSocket ticket.
 *
 * WHY: passing JWTs in WS query strings (?token=<jwt>) is a P1 security
 * risk because reverse proxies log the full upgrade URL, putting the
 * access token in plaintext log files. This hook exchanges the JWT for a
 * 30-second opaque ticket via a normal HTTPS POST, then the WS connection
 * uses ?ticket=<opaque> instead.
 *
 * USAGE:
 *   const { fetchTicket } = useWsTicket();
 *   // inside connect():
 *   const ticket = await fetchTicket();
 *   const ws = new WebSocket(`${baseUrl}?ticket=${ticket}`);
 *
 * If ticket fetch fails (network down, 401) the caller should fall back
 * to the legacy ?token= path or abort. The returned ticket is single-use
 * and expires in 30 s — call fetchTicket() immediately before each new
 * WS connection attempt (including reconnects).
 */
import { useCallback } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { apiFetch } from "../utils/api";

export function useWsTicket() {
  const { accessToken } = useAuth();

  const fetchTicket = useCallback(async (): Promise<string | null> => {
    if (!accessToken) return null;
    try {
      const res = await apiFetch("/api/ws/ticket", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) return null;
      const data = await res.json() as { ticket?: string };
      return data.ticket ?? null;
    } catch {
      return null;
    }
  }, [accessToken]);

  return { fetchTicket };
}
