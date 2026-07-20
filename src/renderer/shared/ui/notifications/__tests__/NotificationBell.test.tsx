import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { NotificationBell } from "../NotificationBell";
import { NotificationContext, type NotificationContextType, type Notification } from "../../../../contexts/notifications";

function makeNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n1", organization_id: "org1", type: "workflow.completed", category: "workflow",
    severity: "success", title: "Workflow done", message: "It finished.", source: null,
    action: null, dismissible: true, read_status: false, read_at: null, archived_at: null,
    expires_at: null, created_at: new Date().toISOString(), ...overrides,
  };
}

function baseCtx(overrides: Partial<NotificationContextType> = {}): NotificationContextType {
  return {
    notifications: [], unreadCount: 0, status: "success", error: null, hasMore: false,
    loadingMore: false, connectionStatus: "live",
    filters: { unreadOnly: false, category: null, search: "" }, setFilters: vi.fn(),
    mutedCategories: [], refetch: vi.fn(), loadMore: vi.fn(), markRead: vi.fn(),
    markAllRead: vi.fn(), archive: vi.fn(), remove: vi.fn(), setMuted: vi.fn(),
    ...overrides,
  };
}

function renderBell(ctx: NotificationContextType) {
  return render(
    <NotificationContext.Provider value={ctx}>
      <NotificationBell />
    </NotificationContext.Provider>,
  );
}

describe("NotificationBell", () => {
  it("shows no badge when unreadCount is 0", () => {
    renderBell(baseCtx({ unreadCount: 0 }));
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
  });

  it("shows the unread count badge and announces it via a live region", () => {
    renderBell(baseCtx({ unreadCount: 3 }));
    expect(screen.getByRole("button", { name: /3 unread/i })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("3 unread notifications");
  });

  it("caps the badge display at 99+", () => {
    renderBell(baseCtx({ unreadCount: 150 }));
    expect(screen.getByText("99+")).toBeInTheDocument();
  });

  it("opens the panel on click and closes it on Escape", () => {
    renderBell(baseCtx({ notifications: [makeNotification()] }));
    const bell = screen.getByRole("button", { name: "Notifications" });

    expect(screen.queryByRole("dialog", { name: "Notifications" })).not.toBeInTheDocument();
    fireEvent.click(bell);
    expect(screen.getByRole("dialog", { name: "Notifications" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Notifications" })).not.toBeInTheDocument();
  });

  it("clicking mark-all-read calls the context action", () => {
    const markAllRead = vi.fn();
    renderBell(baseCtx({ unreadCount: 2, notifications: [makeNotification()], markAllRead }));
    fireEvent.click(screen.getByRole("button", { name: /notifications/i }));
    fireEvent.click(screen.getByRole("button", { name: "Mark all as read" }));
    expect(markAllRead).toHaveBeenCalledTimes(1);
  });

  it("renders EmptyNotifications when the list is empty and status is success", () => {
    renderBell(baseCtx({ notifications: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(screen.getByText(/all caught up/i)).toBeInTheDocument();
  });

  it("renders an ErrorState with retry when status is error", () => {
    const refetch = vi.fn();
    renderBell(baseCtx({ status: "error", error: "Network down", refetch }));
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(screen.getByText("Network down")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("clicking a notification title marks it read", () => {
    const markRead = vi.fn();
    renderBell(baseCtx({ notifications: [makeNotification()], markRead }));
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByText("Workflow done"));
    expect(markRead).toHaveBeenCalledWith("n1");
  });
});
