import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useAgentLiveness } from "../useAgentLiveness";

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

describe("useAgentLiveness — ticket-based WS authentication", () => {
  it("WS URL uses ?ticket= param, not ?token=", async () => {
    const { unmount } = renderHook(() => useAgentLiveness());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("ticket=test-ticket");
    expect(FakeWebSocket.instances[0].url).not.toContain("token=");
    unmount();
  });

  it("WS URL does not contain the JWT", async () => {
    const { unmount } = renderHook(() => useAgentLiveness());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(FakeWebSocket.instances[0].url).not.toContain("fake-jwt");
    unmount();
  });

  it("WS URL targets /ws/system", async () => {
    const { unmount } = renderHook(() => useAgentLiveness());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(FakeWebSocket.instances[0].url).toContain("/ws/system");
    unmount();
  });

  it("ticket failure: no WS created", async () => {
    apiFetchMock.mockResolvedValue({ ok: false });
    const { unmount } = renderHook(() => useAgentLiveness());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(FakeWebSocket.instances).toHaveLength(0);
    unmount();
  });

  it("cancellation during fetchWsTicket prevents WS creation", async () => {
    type TicketResp = { ok: boolean; json: () => Promise<{ ticket: string }> };
    let resolveTicket!: (v: TicketResp) => void;
    const deferred = new Promise<TicketResp>(r => { resolveTicket = r; });
    apiFetchMock.mockReturnValueOnce(deferred);

    const { unmount } = renderHook(() => useAgentLiveness());
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

    const { unmount } = renderHook(() => useAgentLiveness());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(FakeWebSocket.instances).toHaveLength(1);
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

  it("ticket fetch failure schedules backoff without using JWT", async () => {
    vi.useFakeTimers();
    apiFetchMock
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({ ticket: "retry-t" }) });

    const { unmount } = renderHook(() => useAgentLiveness());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(FakeWebSocket.instances).toHaveLength(0);
    const callsAfterFail = apiFetchMock.mock.calls.length;

    await act(async () => {
      vi.advanceTimersByTime(2100);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(apiFetchMock.mock.calls.length).toBeGreaterThan(callsAfterFail);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("ticket=retry-t");
    expect(FakeWebSocket.instances[0].url).not.toContain("token=");
    unmount();
  }, 10000);
});
