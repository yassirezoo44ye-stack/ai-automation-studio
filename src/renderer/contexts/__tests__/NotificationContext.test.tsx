import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { NotificationProvider } from "../NotificationContext";
import { useNotifications, type Notification } from "../notifications";

vi.mock("../AuthContext", () => ({
  useAuth: () => ({ user: { id: "u1", email: "user@example.com" }, accessToken: "fake-jwt" }),
}));

const apiJSONMock = vi.fn();
vi.mock("../../shared/utils/api", () => ({
  API: "",
  apiJSON: (...args: unknown[]) => apiJSONMock(...args),
  authH: () => ({}),
}));

// ── Fake WebSocket ──────────────────────────────────────────────────────────

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
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
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
});

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
