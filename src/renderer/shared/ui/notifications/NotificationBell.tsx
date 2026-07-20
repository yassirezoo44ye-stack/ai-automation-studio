import { useRef, useState } from "react";
import { useNotifications } from "../../../contexts/notifications";
import { NotificationPanel } from "./NotificationPanel";

export function NotificationBell({ collapsed = false }: { collapsed?: boolean }) {
  const { unreadCount } = useNotifications();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <div style={{ position: "relative" }}>
      <button
        ref={triggerRef}
        type="button"
        className="sidebar__item"
        onClick={() => setOpen(v => !v)}
        aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : "Notifications"}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Notifications"
      >
        <span className="sidebar__icon" aria-hidden="true" style={{ position: "relative" }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
          {unreadCount > 0 && (
            <span className="g-notif-badge" aria-hidden="true">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </span>
        {!collapsed && <span className="sidebar__label">Notifications</span>}
      </button>
      {/* aria-live region so screen readers announce new unread counts without
          requiring the panel to be open. */}
      <span className="sr-only" role="status" aria-live="polite">
        {unreadCount > 0 ? `${unreadCount} unread notifications` : ""}
      </span>
      {open && <NotificationPanel onClose={() => setOpen(false)} triggerRef={triggerRef} />}
    </div>
  );
}
