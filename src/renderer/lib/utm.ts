/**
 * Minimal UTM capture + event log.
 * No external analytics platform. Uses sessionStorage only.
 * PII: UTM params only — no user identity collected here.
 */

const UTM_KEY    = "flow_utm";
const EVENTS_KEY = "flow_events";
const MAX_EVENTS = 200;

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
 * Append a named event (with UTM context) to the session event log.
 * Events: "landing_visit" | "cta_click" | "signup_intent"
 */
export function trackEvent(name: string, data?: Record<string, unknown>): void {
  try {
    const raw    = sessionStorage.getItem(EVENTS_KEY);
    const events = raw ? (JSON.parse(raw) as TrackedEvent[]) : [];
    events.push({ name, ts: Date.now(), utm: getUtm(), ...data });
    if (events.length > MAX_EVENTS) events.splice(0, events.length - MAX_EVENTS);
    sessionStorage.setItem(EVENTS_KEY, JSON.stringify(events));
  } catch { /* private mode or quota */ }
}

/** Read all tracked events (for inspection / forwarding to an analytics sink). */
export function getEvents(): TrackedEvent[] {
  try {
    const raw = sessionStorage.getItem(EVENTS_KEY);
    return raw ? (JSON.parse(raw) as TrackedEvent[]) : [];
  } catch { return []; }
}
