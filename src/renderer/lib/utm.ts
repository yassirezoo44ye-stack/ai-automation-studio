/**
 * Minimal UTM capture + event log.
 * sessionStorage: captures UTM params and events for the current tab session.
 * Backend: non-blocking fire-and-forget POST /api/track for durable attribution.
 * PII: UTM params only — no user identity collected here.
 */

const UTM_KEY    = "flow_utm";
const EVENTS_KEY = "flow_events";
const SID_KEY    = "flow_sid";
const MAX_EVENTS = 200;

// Resolve backend base URL at module load time (build-time env var, stripped of trailing slash).
// Empty string → relative URL → works in dev (Vite proxy) and in tests (jsdom, no VITE_API_URL).
const _BACKEND = (
  typeof import.meta !== "undefined" && import.meta.env?.VITE_API_URL
    ? (import.meta.env.VITE_API_URL as string).replace(/\/+$/, "")
    : ""
);

export interface UtmParams {
  utm_source?:   string;
  utm_medium?:   string;
  utm_campaign?: string;
  utm_content?:  string;
}

export interface TrackedEvent {
  name: string;
  ts:   number;
  utm:  UtmParams;
  [key: string]: unknown;
}

/** Read UTM params from URL → persist to sessionStorage → return them. */
export function captureUtm(): UtmParams {
  const params = new URLSearchParams(window.location.search);
  const utm: UtmParams = {};
  for (const key of ["utm_source", "utm_medium", "utm_campaign", "utm_content"] as const) {
    const val = params.get(key);
    if (val) utm[key] = val;
  }
  if (Object.keys(utm).length > 0) {
    try { sessionStorage.setItem(UTM_KEY, JSON.stringify(utm)); } catch { /* private mode */ }
  }
  return utm;
}

/** Return the last captured UTM params (empty object if none). */
export function getUtm(): UtmParams {
  try {
    const raw = sessionStorage.getItem(UTM_KEY);
    return raw ? (JSON.parse(raw) as UtmParams) : {};
  } catch { return {}; }
}

/**
 * Return the anonymous session ID for this browser session.
 * Created on first call, persisted in sessionStorage.
 * Not tied to user identity — safe to include in anonymous events.
 */
export function getSessionId(): string {
  try {
    let sid = sessionStorage.getItem(SID_KEY);
    if (!sid) {
      sid = typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2) + Date.now().toString(36);
      sessionStorage.setItem(SID_KEY, sid);
    }
    return sid;
  } catch {
    return "anonymous";
  }
}

/**
 * Append a named event (with UTM context) to the session event log,
 * then fire a non-blocking POST to /api/track for durable attribution.
 * Events: "landing_visit" | "cta_click" | "signup"
 * Tracking failure never blocks the caller.
 */
export function trackEvent(name: string, data?: Record<string, unknown>): void {
  // 1. sessionStorage log (existing behaviour — best-effort)
  try {
    const raw    = sessionStorage.getItem(EVENTS_KEY);
    const events = raw ? (JSON.parse(raw) as TrackedEvent[]) : [];
    events.push({ name, ts: Date.now(), utm: getUtm(), ...data });
    if (events.length > MAX_EVENTS) events.splice(0, events.length - MAX_EVENTS);
    sessionStorage.setItem(EVENTS_KEY, JSON.stringify(events));
  } catch { /* private mode or quota */ }

  // 2. Backend attribution (fire-and-forget — never throws, never awaited)
  _sendToBackend(name);
}

/** Read all tracked events (for inspection / forwarding to an analytics sink). */
export function getEvents(): TrackedEvent[] {
  try {
    const raw = sessionStorage.getItem(EVENTS_KEY);
    return raw ? (JSON.parse(raw) as TrackedEvent[]) : [];
  } catch { return []; }
}

// ── Internal ──────────────────────────────────────────────────────────────────

function _sendToBackend(name: string): void {
  const utm = getUtm();
  const payload = {
    event:        name,
    session_id:   getSessionId(),
    utm_source:   utm.utm_source,
    utm_medium:   utm.utm_medium,
    utm_campaign: utm.utm_campaign,
    utm_content:  utm.utm_content,
  };
  try {
    fetch(`${_BACKEND}/api/track`, {
      method:    "POST",
      headers:   { "Content-Type": "application/json" },
      body:      JSON.stringify(payload),
      keepalive: true,
    }).catch(() => { /* attribution failure is silent */ });
  } catch { /* fetch unavailable (SSR/tests) — ignore */ }
}
