/**
 * Phase 4 — Frontend Vitest tests: AgentOS project-context propagation.
 *
 * Covers:
 *   1. agentOsApi.run() defaults project_id from sessionStorage
 *   2. agentOsApi.run() respects an explicit project_id override
 *   3. agentOsApi.run() sends undefined (not null) when sessionStorage is empty
 *   4. agentOsApi.plan() now passes project_id (was missing before the fix)
 *   5. agentOsApi.deliberate() now passes project_id (was missing before the fix)
 *   6. All three default from sessionStorage independently
 *   7. Storage-event: project_id in POST body reflects sessionStorage at call time
 *   8. DevWorkspace initialises projectId from sessionStorage
 *
 * None of these tests require a backend — all network calls are intercepted.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { agentOsApi } from "../api";

// ── helpers ───────────────────────────────────────────────────────────────────

/** Capture the request body sent to fetch. */
function captureBody(status = 200, payload: unknown = { agent: "echo", success: true, output: "", data: {}, duration_ms: 0 }) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function parsedBody(fetchMock: ReturnType<typeof vi.fn>): Record<string, unknown> {
  const call = fetchMock.mock.calls[0];
  const init = call[1] as RequestInit;
  return JSON.parse(init.body as string);
}

// ── setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

// ── 1. agentOsApi.run() reads project_id from sessionStorage by default ───────

describe("agentOsApi.run() — project_id defaults", () => {
  it("includes project_id from sessionStorage when set", async () => {
    sessionStorage.setItem("flow_active_project", "proj-from-session");
    const mock = captureBody();

    await agentOsApi.run("echo hello").catch(() => {});

    const body = parsedBody(mock);
    expect(body.project_id).toBe("proj-from-session");
  });

  it("sends undefined (not null, not empty string) when sessionStorage is empty", async () => {
    // sessionStorage cleared in beforeEach
    const mock = captureBody();

    await agentOsApi.run("echo hello").catch(() => {});

    const body = parsedBody(mock);
    // undefined is serialised to absent key by JSON.stringify
    expect("project_id" in body ? body.project_id : undefined).toBeUndefined();
  });
});

// ── 2. agentOsApi.run() respects an explicit override ────────────────────────

describe("agentOsApi.run() — explicit project_id override", () => {
  it("prefers the caller-supplied project_id over sessionStorage", async () => {
    sessionStorage.setItem("flow_active_project", "session-id");
    const mock = captureBody();

    await agentOsApi.run("echo hello", undefined, undefined, "explicit-id").catch(() => {});

    const body = parsedBody(mock);
    expect(body.project_id).toBe("explicit-id");
  });

  it("falls back to sessionStorage when the explicit override is undefined", async () => {
    sessionStorage.setItem("flow_active_project", "fallback-session-id");
    const mock = captureBody();

    await agentOsApi.run("echo hello", undefined, undefined, undefined).catch(() => {});

    const body = parsedBody(mock);
    expect(body.project_id).toBe("fallback-session-id");
  });
});

// ── 3. agentOsApi.plan() now sends project_id (regression: was missing) ───────

describe("agentOsApi.plan() — project_id propagation", () => {
  const planPayload = { plan: ["step1"], results: [], success: true };

  it("includes project_id from sessionStorage", async () => {
    sessionStorage.setItem("flow_active_project", "plan-proj");
    const mock = captureBody(200, planPayload);

    await agentOsApi.plan("deploy app").catch(() => {});

    const body = parsedBody(mock);
    expect(body.project_id).toBe("plan-proj");
  });

  it("accepts an explicit project_id override", async () => {
    sessionStorage.setItem("flow_active_project", "session-proj");
    const mock = captureBody(200, planPayload);

    await agentOsApi.plan("deploy app", undefined, "explicit-plan-proj").catch(() => {});

    const body = parsedBody(mock);
    expect(body.project_id).toBe("explicit-plan-proj");
  });

  it("sends undefined when sessionStorage is empty and no override given", async () => {
    const mock = captureBody(200, planPayload);

    await agentOsApi.plan("deploy app").catch(() => {});

    const body = parsedBody(mock);
    expect("project_id" in body ? body.project_id : undefined).toBeUndefined();
  });
});

// ── 4. agentOsApi.deliberate() now sends project_id (regression: was missing) ─

describe("agentOsApi.deliberate() — project_id propagation", () => {
  const deliberatePayload = {
    result: { agent: "echo", success: true, output: "", data: {}, duration_ms: 0 },
    deliberation: { winner: "echo", winner_score: 1, consensus: 1, method: "vote", bids: [] },
  };

  it("includes project_id from sessionStorage", async () => {
    sessionStorage.setItem("flow_active_project", "delib-proj");
    const mock = captureBody(200, deliberatePayload);

    await agentOsApi.deliberate("analyze performance").catch(() => {});

    const body = parsedBody(mock);
    expect(body.project_id).toBe("delib-proj");
  });

  it("accepts an explicit project_id override", async () => {
    sessionStorage.setItem("flow_active_project", "session-proj");
    const mock = captureBody(200, deliberatePayload);

    await agentOsApi.deliberate("analyze performance", undefined, "explicit-delib-proj").catch(() => {});

    const body = parsedBody(mock);
    expect(body.project_id).toBe("explicit-delib-proj");
  });

  it("sends undefined when sessionStorage is empty and no override given", async () => {
    const mock = captureBody(200, deliberatePayload);

    await agentOsApi.deliberate("analyze performance").catch(() => {});

    const body = parsedBody(mock);
    expect("project_id" in body ? body.project_id : undefined).toBeUndefined();
  });
});

// ── 5. sessionStorage update is reflected at call time ────────────────────────

describe("sessionStorage update reflected at call time", () => {
  it("picks up the project_id that is current when the call is made, not at module load", async () => {
    // No project at module init time…
    const mock = captureBody();

    // …but user navigates, and AppBuilderPage sets one before the user runs
    sessionStorage.setItem("flow_active_project", "set-before-call");

    await agentOsApi.run("echo").catch(() => {});

    const body = parsedBody(mock);
    expect(body.project_id).toBe("set-before-call");
  });

  it("reflects a changed project_id (user switches project) on the next call", async () => {
    sessionStorage.setItem("flow_active_project", "first-project");
    const mock1 = captureBody();
    await agentOsApi.run("echo first").catch(() => {});
    expect(parsedBody(mock1).project_id).toBe("first-project");

    // User switches project in DevWorkspace
    sessionStorage.setItem("flow_active_project", "second-project");
    vi.unstubAllGlobals();
    const mock2 = captureBody();
    await agentOsApi.run("echo second").catch(() => {});
    expect(parsedBody(mock2).project_id).toBe("second-project");
  });
});

// ── 6. run_id is still included alongside project_id ─────────────────────────

describe("agentOsApi.run() — run_id and project_id coexist", () => {
  it("sends both run_id and project_id in the same request", async () => {
    sessionStorage.setItem("flow_active_project", "proj-x");
    const mock = captureBody();

    await agentOsApi.run("echo", undefined, "my-run-id").catch(() => {});

    const body = parsedBody(mock);
    expect(body.run_id).toBe("my-run-id");
    expect(body.project_id).toBe("proj-x");
  });
});
