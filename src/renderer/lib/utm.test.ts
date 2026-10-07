/**
 * Tests for utm.ts attribution module.
 *
 * Covers:
 * - UTM extraction from URL
 * - landing_visit / cta_click / signup events in sessionStorage
 * - missing UTM parameters
 * - analytics endpoint unavailable (fetch rejects)
 * - tracking failure does NOT break the caller
 * - no sensitive data (password, token, email) transmitted to backend
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Helpers ──────────────────────────────────────────────────────────────────

function setSearch(query: string) {
  Object.defineProperty(window, "location", {
    value: { ...window.location, search: query },
    writable: true,
    configurable: true,
  });
}

// ── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  sessionStorage.clear();
  setSearch("");
  vi.restoreAllMocks();
  vi.resetModules();
});

// ── 1. UTM extraction ─────────────────────────────────────────────────────────

describe("captureUtm", () => {
  it("extracts all four UTM params from URL", async () => {
    setSearch("?utm_source=meta&utm_medium=paid_social&utm_campaign=agency_test&utm_content=creative_a");
    const { captureUtm } = await import("./utm");
    const utm = captureUtm();
    expect(utm).toEqual({
      utm_source:   "meta",
      utm_medium:   "paid_social",
      utm_campaign: "agency_test",
      utm_content:  "creative_a",
    });
  });

  it("persists UTM params to sessionStorage", async () => {
    setSearch("?utm_source=google&utm_campaign=brand");
    const { captureUtm } = await import("./utm");
    captureUtm();
    const stored = JSON.parse(sessionStorage.getItem("flow_utm") ?? "{}");
    expect(stored.utm_source).toBe("google");
    expect(stored.utm_campaign).toBe("brand");
  });

  it("returns empty object when no UTM params present", async () => {
    setSearch("");
    const { captureUtm } = await import("./utm");
    const utm = captureUtm();
    expect(utm).toEqual({});
  });

  it("ignores unrelated query params", async () => {
    setSearch("?ref=homepage&foo=bar");
    const { captureUtm } = await import("./utm");
    const utm = captureUtm();
    expect(Object.keys(utm)).toHaveLength(0);
  });
});

// ── 2. landing_visit event ────────────────────────────────────────────────────

describe("trackEvent landing_visit", () => {
  it("stores landing_visit in sessionStorage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    const { trackEvent, getEvents } = await import("./utm");
    trackEvent("landing_visit");
    const events = getEvents();
    expect(events).toHaveLength(1);
    expect(events[0].name).toBe("landing_visit");
    expect(typeof events[0].ts).toBe("number");
  });

  it("attaches captured UTM to the event", async () => {
    setSearch("?utm_source=meta");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    const { captureUtm, trackEvent, getEvents } = await import("./utm");
    captureUtm();
    trackEvent("landing_visit");
    const events = getEvents();
    expect(events[0].utm.utm_source).toBe("meta");
  });
});

// ── 3. cta_click event ────────────────────────────────────────────────────────

describe("trackEvent cta_click", () => {
  it("stores cta_click with action in sessionStorage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    const { trackEvent, getEvents } = await import("./utm");
    trackEvent("cta_click", { action: "signup" });
    const events = getEvents();
    expect(events[0].name).toBe("cta_click");
    expect(events[0].action).toBe("signup");
  });
});

// ── 4. signup event ───────────────────────────────────────────────────────────

describe("trackEvent signup", () => {
  it("stores signup event in sessionStorage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    const { trackEvent, getEvents } = await import("./utm");
    trackEvent("signup");
    const events = getEvents();
    expect(events.some(e => e.name === "signup")).toBe(true);
  });
});

// ── 5. missing UTM parameters ────────────────────────────────────────────────

describe("missing UTM parameters", () => {
  it("getUtm returns empty object when nothing stored", async () => {
    const { getUtm } = await import("./utm");
    expect(getUtm()).toEqual({});
  });

  it("trackEvent works without any UTM params", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    const { trackEvent, getEvents } = await import("./utm");
    expect(() => trackEvent("landing_visit")).not.toThrow();
    expect(getEvents()).toHaveLength(1);
  });
});

// ── 6. analytics endpoint unavailable ────────────────────────────────────────

describe("analytics endpoint unavailable", () => {
  it("does not throw when fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    const { trackEvent } = await import("./utm");
    expect(() => trackEvent("landing_visit")).not.toThrow();
  });

  it("does not throw when fetch throws synchronously", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => { throw new Error("fetch unavailable"); }));
    const { trackEvent } = await import("./utm");
    expect(() => trackEvent("cta_click", { action: "signup" })).not.toThrow();
  });
});

// ── 7. tracking failure does not break CTA ────────────────────────────────────

describe("failure does not block CTA", () => {
  it("onSignUp callback fires even when fetch is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const { trackEvent } = await import("./utm");
    const onSignUp = vi.fn();

    trackEvent("cta_click", { action: "signup" });
    onSignUp();

    expect(onSignUp).toHaveBeenCalledOnce();
  });

  it("sessionStorage write failure does not propagate", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    const { trackEvent } = await import("./utm");
    expect(() => trackEvent("landing_visit")).not.toThrow();
  });
});

// ── 8. no sensitive data transmitted ─────────────────────────────────────────

describe("no sensitive data in backend payload", () => {
  it("POST /api/track payload contains only allowed fields", async () => {
    let captured: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      captured = init;
      return Promise.resolve({ ok: true });
    }));

    setSearch("?utm_source=meta&utm_medium=cpc");
    const { captureUtm, trackEvent } = await import("./utm");
    captureUtm();
    trackEvent("signup");

    await new Promise(resolve => setTimeout(resolve, 0));

    expect(captured).toBeDefined();
    const body = JSON.parse(captured!.body as string);

    expect(body).toHaveProperty("event", "signup");
    expect(body).toHaveProperty("session_id");
    expect(body).toHaveProperty("utm_source", "meta");
    expect(body).toHaveProperty("utm_medium", "cpc");

    expect(body).not.toHaveProperty("password");
    expect(body).not.toHaveProperty("email");
    expect(body).not.toHaveProperty("token");
    expect(body).not.toHaveProperty("name");
  });

  it("session_id contains no personal information", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    const { getSessionId } = await import("./utm");
    const sid = getSessionId();
    expect(sid).not.toContain("@");
    expect(sid.length).toBeGreaterThan(0);
    expect(sid.length).toBeLessThanOrEqual(64);
  });
});
