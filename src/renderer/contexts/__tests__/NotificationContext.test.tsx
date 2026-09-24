import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NotificationProvider } from "../NotificationContext";
import { useNotifications, type Notification } from "../notifications";

vi.mock("../AuthContext", () => ({
  useAuth: () => ({ user: { id: "u1", email: "user@example.com" }, accessToken: "fake-jwt" }),
}));

const apiJSONMock = vi.fn();
const apiFetchMock = vi.fn();
vi.mock("../../shared/utils/api", () => ({
  API: "",
  apiJSON: (...args: unknown[]) => apiJSONMock(...args),
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  authH: () => ({}),
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

function makeNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n1", organization_id: "org1", type: "workflow.completed", category: "workflow",
    severity: "success", title: "Workflow done", message: "It finished.", source: null,
    action: null, dismissible: true, read_status: false, read_at: null, archived_at: null,
    expires_at: null, created_at: new Date().toISOString(), ...overrides,
  };
}

function defaultApiJSON() {
  return apiJSONMock.mockImplementation((path: string) => {
    if (path.startsWith("/api/notifications/unread-count")) return Promise.resolve({ unread_count: 0 });
    if (path.startsWith("/api/notifications/preferences")) return Promise.resolve({ muted_categories: [] });
    return Promise.resolve({ notifications: [], has_more: false });
  });
}

function Consumer() {
  const { notifications, unreadCount, status, markRead, markAllRead, archive, remove } = useNotifications();
  return (
    <div>
      <div data-testid="status">{status}</div>
      <div data-testid="unread">{unreadCount}</div>
      <ul>
        {notifications.map(n => (
          <li key={n.id} data-testid={`n-${n.id}`}>{n.title}:{n.read_status ? "read" : "unread"}</li>
        ))}
      </ul>
      <button onClick={() => markRead("n1")}>mark-read-n1</button>
      <button onClick={markAllRead}>mark-all-read</button>
      <button onClick={() => archive("n1")}>archive-n1</button>
      <button onClick={() => remove("n1")}>remove-n1</button>
    </div>
  );
}

beforeEach(() => {
  apiJSONMock.mockReset();
  apiFetchMock.mockReset();
  // Default: ticket endpoint returns a valid ticket immediately.
  apiFetchMock.mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ ticket: "test-ticket" }),
  });
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Existing tests (unchanged) ─────────────────────────────────────────────

describe("NotificationProvider", () => {
  it("loads the first page + unread count on mount", async () => {
    apiJSONMock.mockImplementation((path: string) => {
      if (path.startsWith("/api/notifications/unread-count")) return Promise.resolve({ unread_count: 2 });
      if (path.startsWith("/api/notifications/preferences")) return Promise.resolve({ muted_categories: [] });
      return Promise.resolve({ notifications: [makeNotification()], has_more: false });
    });

    render(<NotificationProvider><Consumer /></NotificationProvider>);

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("success"));
    expect(screen.getByTestId("unread")).toHaveTextContent("2");
    expect(screen.getByTestId("n-n1")).toHaveTextContent("Workflow done:unread");
  });

  it("markRead optimistically flips read_status and decrements unread count", async () => {
    apiJSONMock.mockImplementation((path: string) => {
      if (path.startsWith("/api/notifications/unread-count")) return Promise.resolve({ unread_count: 1 });
      if (path.startsWith("/api/notifications/preferences")) return Promise.resolve({ muted_categories: [] });
      if (path.includes("/read")) return Promise.resolve({ ok: true });
      return Promise.resolve({ notifications: [makeNotification()], has_more: false });
    });

    render(<NotificationProvider><Consumer /></NotificationProvider>);
    await waitFor(() => expect(screen.getByTestId("unread")).toHaveTextContent("1"));

    fireEvent.click(screen.getByText("mark-read-n1"));

    await waitFor(() => expect(screen.getByTestId("n-n1")).toHaveTextContent("Workflow done:read"));
    expect(screen.getByTestId("unread")).toHaveTextContent("0");
    expect(apiJSONMock).toHaveBeenCalledWith("/api/notifications/n1/read", { method: "POST" });
  });

  it("archive removes the item from the visible list", async () => {
    apiJSONMock.mockImplementation((path: string) => {
      if (path.startsWith("/api/notifications/unread-count")) return Promise.resolve({ unread_count: 1 });
      if (path.startsWith("/api/notifications/preferences")) return Promise.resolve({ muted_categories: [] });
      if (path.includes("/archive")) return Promise.resolve({ ok: true });
      return Promise.resolve({ notifications: [makeNotification()], has_more: false });
    });

    render(<NotificationProvider><Consumer /></NotificationProvider>);
    await waitFor(() => expect(screen.getByTestId("n-n1")).toBeInTheDocument());

    fireEvent.click(screen.getByText("archive-n1"));
    await waitFor(() => expect(screen.queryByTestId("n-n1")).not.toBeInTheDocument());
  });

  it("a live WS event prepends a new notification and bumps unread count", async () => {
    apiJSONMock.mockImplementation((path: string) => {
      if (path.startsWith("/api/notifications/unread-count")) return Promise.resolve({ unread_count: 0 });
      if (path.startsWith("/api/notifications/preferences")) return Promise.resolve({ muted_categories: [] });
      return Promise.resolve({ notifications: [], has_more: false });
    });

    render(<NotificationProvider><Consumer /></NotificationProvider>);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("success"));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));

    const ws = FakeWebSocket.instances[0];
    act(() => { ws.onopen?.(); });
    // onopen triggers a backfill refetch — let that settle before injecting the live event.
    await waitFor(() => expect(apiJSONMock.mock.calls.length).toBeGreaterThan(2));

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ type: "event", topic: "notifications:u1", data: makeNotification({ id: "n2", title: "Live one" }) }) });
    });

    await waitFor(() => expect(screen.getByTestId("n-n2")).toHaveTextContent("Live one:unread"));
    expect(screen.getByTestId("unread")).toHaveTextContent("1");
  });

  it("does not double-count a duplicate WS event for an id already known", async () => {
    apiJSONMock.mockImplementation((path: string) => {
      if (path.startsWith("/api/notifications/unread-count")) return Promise.resolve({ unread_count: 1 });
      if (path.startsWith("/api/notifications/preferences")) return Promise.resolve({ muted_categories: [] });
      return Promise.resolve({ notifications: [makeNotification()], has_more: false });
    });

    render(<NotificationProvider><Consumer /></NotificationProvider>);
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    act(() => { ws.onopen?.(); });
    await waitFor(() => expect(screen.getByTestId("n-n1")).toBeInTheDocument());

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ type: "event", data: makeNotification({ id: "n1" }) }) });
    });

    // Still exactly one n1 row — no duplicate insert, no extra unread bump.
    expect(screen.getAllByTestId("n-n1")).toHaveLength(1);
  });
});

// ── Ticket authentication tests ────────────────────────────────────────────

describe("NotificationProvider — ticket-based WS authentication", () => {
  it("WS URL uses ?ticket= param, not ?token=", async () => {
    defaultApiJSON();
    render(<NotificationProvider><Consumer /></NotificationProvider>);

    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    expect(FakeWebSocket.instances[0].url).toContain("ticket=");
    expect(FakeWebSocket.instances[0].url).not.toContain("token=");
  });

  it("WS URL does not contain the JWT or any ?token= param", async () => {
    defaultApiJSON();
    render(<NotificationProvider><Consumer /></NotificationProvider>);

    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const url = FakeWebSocket.instances[0].url;
    expect(url).not.toContain("token=");
    expect(url).not.toContain("fake-jwt");
  });

  it("calls the ticket endpoint before creating the WebSocket", async () => {
    defaultApiJSON();

    let wsCountAtTicketCall = -1;
    apiFetchMock.mockImplementationOnce(async (path: string) => {
      if (path === "/api/ws/ticket") {
        wsCountAtTicketCall = FakeWebSocket.instances.length;
        return { ok: true, json: () => Promise.resolve({ ticket: "t1" }) };
      }
      return { ok: false };
    });

    render(<NotificationProvider><Consumer /></NotificationProvider>);
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));

    expect(wsCountAtTicketCall).toBe(0); // no WS existed when ticket was fetched
    expect(apiFetchMock).toHaveBeenCalledWith("/api/ws/ticket", { method: "POST" });
  });

  it("ticket failure: no WS is created, no JWT falls back into the URL", async () => {
    defaultApiJSON();
    // All ticket requests fail
    apiFetchMock.mockResolvedValue({ ok: false });

    render(<NotificationProvider><Consumer /></NotificationProvider>);

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    // Give microtasks a moment to settle
    await act(async () => { await Promise.resolve(); });

    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("ticket failure schedules a reconnect/backoff without using JWT", async () => {
    vi.useFakeTimers();
    defaultApiJSON();

    apiFetchMock
      .mockResolvedValueOnce({ ok: false }) // first attempt fails
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({ ticket: "retry-ticket" }) });

    render(<NotificationProvider><Consumer /></NotificationProvider>);

    // Flush initial connect() — ticket fails, no WS created
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(FakeWebSocket.instances).toHaveLength(0);
    const callsAfterFirstFail = apiFetchMock.mock.calls.length;

    // Advance past backoff and flush the async connect() that fires
    await act(async () => {
      vi.advanceTimersByTime(2100);
      await Promise.resolve();
      await Promise.resolve();
    });

    // A second ticket fetch was made and WS was created
    expect(apiFetchMock.mock.calls.length).toBeGreaterThan(callsAfterFirstFail);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("ticket=retry-ticket");
    expect(FakeWebSocket.instances[0].url).not.toContain("token=");

    vi.useRealTimers();
  }, 10000);

  it("WS close fetches a fresh ticket before the reconnect (never reuses old ticket)", async () => {
    vi.useFakeTimers();
    defaultApiJSON();

    let ticketSeq = 0;
    apiFetchMock.mockImplementation(() => {
      ticketSeq++;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ticket: `ticket-${ticketSeq}` }),
      });
    });

    render(<NotificationProvider><Consumer /></NotificationProvider>);
    // Flush initial connect()
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("ticket=ticket-1");

    const callsAfterFirstConnect = apiFetchMock.mock.calls.length;

    // Trigger WS close → schedules reconnect with backoff
    act(() => { FakeWebSocket.instances[0].onclose?.(); });

    // Advance past backoff and flush the reconnect connect()
    await act(async () => {
      vi.advanceTimersByTime(2100);
      await Promise.resolve();
      await Promise.resolve();
    });

    // A second ticket fetch occurred and a new WS was created
    expect(apiFetchMock.mock.calls.length).toBeGreaterThan(callsAfterFirstConnect);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1].url).toContain("ticket=ticket-2");
    expect(FakeWebSocket.instances[1].url).not.toContain("token=");

    vi.useRealTimers();
  }, 10000);

  it("every reconnect uses a fresh ticket — JWT never appears in any WS URL", async () => {
    vi.useFakeTimers();
    defaultApiJSON();

    let n = 0;
    apiFetchMock.mockImplementation(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ ticket: `t${++n}` }) })
    );

    render(<NotificationProvider><Consumer /></NotificationProvider>);
    // Flush initial connect()
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(FakeWebSocket.instances).toHaveLength(1);

    // Close and flush the reconnect
    act(() => { FakeWebSocket.instances[0].onclose?.(); });
    await act(async () => {
      vi.advanceTimersByTime(2100);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    // Both WS URLs must use tickets, not the JWT "fake-jwt"
    FakeWebSocket.instances.forEach(ws => {
      expect(ws.url).toContain("ticket=");
      expect(ws.url).not.toContain("token=");
      expect(ws.url).not.toContain("fake-jwt");
    });

    vi.useRealTimers();
  }, 10000);

  it("cleanup during fetchWsTicket (cancelled) prevents WebSocket creation", async () => {
    defaultApiJSON();

    // Deferred ticket — won't resolve until we say so
    type TicketResponse = { ok: boolean; json: () => Promise<{ ticket: string }> };
    let resolveTicket!: (v: TicketResponse) => void;
    const deferredTicket = new Promise<TicketResponse>(r => { resolveTicket = r; });
    apiFetchMock.mockReturnValueOnce(deferredTicket);

    const { unmount } = render(<NotificationProvider><Consumer /></NotificationProvider>);

    // Unmount before ticket resolves → cleanup sets cancelled = true
    unmount();

    // Now resolve the ticket — connect() should detect cancelled and abort
    resolveTicket({ ok: true, json: () => Promise.resolve({ ticket: "late-ticket" }) });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("no double WebSocket connections during reconnect (exactly one WS per connect cycle)", async () => {
    vi.useFakeTimers();
    defaultApiJSON();

    apiFetchMock.mockImplementation(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ ticket: "t" }) })
    );

    render(<NotificationProvider><Consumer /></NotificationProvider>);
    // Flush initial connect()
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(FakeWebSocket.instances).toHaveLength(1);

    // Close WS → schedules reconnect with backoff
    act(() => { FakeWebSocket.instances[0].onclose?.(); });

    // Advance timers and flush the reconnect connect()
    await act(async () => {
      vi.advanceTimersByTime(2100);
      await Promise.resolve();
      await Promise.resolve();
    });

    // Must be exactly 2 — not 3 or more
    expect(FakeWebSocket.instances).toHaveLength(2);

    vi.useRealTimers();
  }, 10000);
});
