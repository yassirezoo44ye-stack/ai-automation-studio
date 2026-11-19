import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import * as Organizations from "../../../../contexts/OrgContext";
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
    presenceDeltas: new Map(),
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
    expect(refetch).toHaveBeenCalledTimes(2);
  });

  it("clicking a notification title marks it read", () => {
    const markRead = vi.fn();
    renderBell(baseCtx({ notifications: [makeNotification()], markRead }));
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByText("Workflow done"));
    expect(markRead).toHaveBeenCalledWith("n1");
  });
});


describe("Notification popup interactions", () => {
  it("renders outside clipped layout containers and keeps the settings dialog open while editing", async () => {
    const setMuted = vi.fn();
    const { container } = renderBell(baseCtx({ setMuted }));
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    const panel = screen.getByRole("dialog", { name: "Notifications" });
    expect(container).not.toContainElement(panel);
    fireEvent.click(screen.getByRole("button", { name: "Notification settings" }));
    const checkbox = screen.getByRole("checkbox", { name: "Notify me about Workflows" });
    fireEvent.mouseDown(checkbox);
    fireEvent.click(checkbox);
    expect(setMuted).toHaveBeenCalledWith("workflow", true);
    expect(screen.getByRole("dialog", { name: "Notification settings" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Notification settings" })).not.toBeInTheDocument());
    expect(panel).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Notification settings" })).toHaveFocus();
  });

  it("preserves notification destination query parameters", () => {
    renderBell(baseCtx({ notifications: [makeNotification({ action: { href: "/automation?run=run-123", label: "View run" } })] }));
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByText("Workflow done"));
    expect(window.location.pathname).toBe("/automation");
    expect(window.location.search).toBe("?run=run-123");
    window.history.replaceState(null, "", "/");
  });
});


afterEach(() => { vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); });

describe("Notification destination scopes", () => {
  function organizationContext(known: boolean) {
    const org = { id: "org1", name: "Linked workspace", slug: "linked", kind: "organization" as const, plan: "free", created_at: "2026-11-19" };
    return { orgs: known ? [org] : [], currentOrgId: "other", currentOrg: null, loading: false,
      setCurrentOrgId: vi.fn(), refreshOrgs: vi.fn(async () => {}), createOrg: vi.fn(async () => org) };
  }

  it("switches to a known membership before opening the notification destination", () => {
    const context = organizationContext(true);
    vi.spyOn(Organizations, "useOrg").mockReturnValue(context);
    renderBell(baseCtx({ notifications: [makeNotification({ action: { href: "/automation?run=run-1", label: "View run" } })] }));
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByText("Workflow done"));
    expect(context.setCurrentOrgId).toHaveBeenCalledWith("org1");
    expect(window.location.pathname + window.location.search).toBe("/automation?run=run-1");
  });

  it("reports a workspace the user cannot select instead of opening the wrong organization", () => {
    const context = organizationContext(false);
    vi.spyOn(Organizations, "useOrg").mockReturnValue(context);
    renderBell(baseCtx({ notifications: [makeNotification({ action: { href: "/automation?run=run-1", label: "View run" } })] }));
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByText("Workflow done"));
    expect(screen.getByText("The linked workspace is unavailable. Refresh or check your access.")).toBeInTheDocument();
    expect(context.setCurrentOrgId).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/");
  });

  it.each(["https://other.example/automation", "javascript:alert(1)", "http://[", "/automation/not-a-route"])("ignores an invalid destination %s", href => {
    renderBell(baseCtx({ notifications: [makeNotification({ action: { href, label: "Invalid target" } })] }));
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByText("Workflow done"));
    expect(window.location.pathname).toBe("/");
    expect(screen.getByRole("dialog", { name: "Notifications" })).toBeInTheDocument();
  });
});
