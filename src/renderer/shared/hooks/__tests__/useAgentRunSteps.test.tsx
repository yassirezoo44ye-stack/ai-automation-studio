import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useAgentRunSteps } from "../useAgentRunSteps";

vi.mock("../../../contexts/AuthContext", () => ({
  useAuth: () => ({ accessToken: "fake-jwt" }),
}));

const apiFetchMock = vi.fn();
vi.mock("../../utils/api", () => ({
  API: "",
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

// ── Fake WebSocket ──────────────────────────────────────────────────────────

class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];
  url: string;
  readyState = FakeWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  close() { this.closed = true; this.onclose?.(); }
  send() {}
}

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ ticket: "test-ticket" }),
  });
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("useAgentRunSteps — ticket-based WS authentication", () => {
  it("WS URL contains runId and ?ticket=", async () => {
    const { unmount } = renderHook(() => useAgentRunSteps("run-abc-123"));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("/ws/system/run-abc-123");
    expect(FakeWebSocket.instances[0].url).toContain("ticket=test-ticket");
    expect(FakeWebSocket.instances[0].url).not.toContain("token=");
    unmount();
  });

  it("WS URL does not contain the JWT", async () => {
    const { unmount } = renderHook(() => useAgentRunSteps("run-abc-123"));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(FakeWebSocket.instances[0].url).not.toContain("fake-jwt");
    unmount();
  });

  it("null runId: no WS created", async () => {
    const { unmount } = renderHook(() => useAgentRunSteps(null));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(FakeWebSocket.instances).toHaveLength(0);
    unmount();
  });

  it("ticket failure: no WS created", async () => {
    apiFetchMock.mockResolvedValue({ ok: false });
    const { unmount } = renderHook(() => useAgentRunSteps("run-xyz"));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(FakeWebSocket.instances).toHaveLength(0);
    unmount();
  });

  it("cancellation during fetchWsTicket prevents WS creation", async () => {
    type TicketResp = { ok: boolean; json: () => Promise<{ ticket: string }> };
    let resolveTicket!: (v: TicketResp) => void;
    const deferred = new Promise<TicketResp>(r => { resolveTicket = r; });
    apiFetchMock.mockReturnValueOnce(deferred);

    const { unmount } = renderHook(() => useAgentRunSteps("run-cancel"));
    unmount(); // cancels before ticket resolves
    resolveTicket({ ok: true, json: () => Promise.resolve({ ticket: "late" }) });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("reconnect fetches a fresh ticket — no JWT fallback", async () => {
    vi.useFakeTimers();
    let n = 0;
    apiFetchMock.mockImplementation(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ ticket: `t${++n}` }) })
    );

    const { unmount } = renderHook(() => useAgentRunSteps("run-r1"));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("/ws/system/run-r1");
    expect(FakeWebSocket.instances[0].url).toContain("ticket=t1");

    act(() => { FakeWebSocket.instances[0].onclose?.(); });

    await act(async () => {
      vi.advanceTimersByTime(2100);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1].url).toContain("ticket=t2");
    expect(FakeWebSocket.instances[1].url).not.toContain("token=");
    unmount();
  }, 10000);

  it("runId change reconnects to the new run's endpoint with a fresh ticket", async () => {
    let n = 0;
    apiFetchMock.mockImplementation(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ ticket: `t${++n}` }) })
    );

    const { unmount, rerender } = renderHook(
      ({ runId }: { runId: string }) => useAgentRunSteps(runId),
      { initialProps: { runId: "run-A" } }
    );
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("/ws/system/run-A");

    rerender({ runId: "run-B" });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    // After rerender a second WS is created for the new runId
    const wsB = FakeWebSocket.instances.find(ws => ws.url.includes("run-B"));
    expect(wsB).toBeDefined();
    expect(wsB!.url).toContain("ticket=");
    expect(wsB!.url).not.toContain("token=");
    unmount();
  });
});
