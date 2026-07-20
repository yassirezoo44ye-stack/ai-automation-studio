import { memo } from "react";
import type { KeyboardEvent } from "react";
import type { Notification } from "../../../contexts/notifications";
import { relTime } from "../../utils/time";

const SEVERITY_ICON: Record<Notification["severity"], string> = {
  success: "✓", info: "i", warning: "!", error: "✕",
};

function NotificationItemImpl({
  notification, focused, onSelect, onArchive, onRemove, onNavigate, itemRef,
}: {
  notification: Notification;
  focused: boolean;
  onSelect: (id: string) => void;
  onArchive: (id: string) => void;
  onRemove: (id: string) => void;
  onNavigate: (href: string) => void;
  itemRef: (el: HTMLDivElement | null) => void;
}) {
  const n = notification;

  function activate() {
    if (!n.read_status) onSelect(n.id);
    if (n.action) onNavigate(n.action.href);
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter") { e.preventDefault(); activate(); }
  }

  return (
    <div
      ref={itemRef}
      role="option"
      aria-selected={focused}
      tabIndex={focused ? 0 : -1}
      className={`g-notif-item ${n.read_status ? "" : "g-notif-item--unread"}`}
      onClick={activate}
      onKeyDown={onKeyDown}
    >
      <span className={`g-notif-item__icon g-notif-item__icon--${n.severity}`} aria-hidden="true">
        {SEVERITY_ICON[n.severity]}
      </span>
      <div className="g-notif-item__body">
        <div className="g-notif-item__title">{n.title}</div>
        <div className="g-notif-item__message">{n.message}</div>
        <div className="g-notif-item__meta">
          <span>{relTime(n.created_at)}</span>
          {n.action && <span className="g-notif-item__action-hint">{n.action.label} →</span>}
        </div>
      </div>
      {!n.read_status && <span className="g-notif-item__dot" aria-label="Unread" />}
      <div className="g-notif-item__ops">
        <button
          type="button" className="g-notif-item__op"
          onClick={e => { e.stopPropagation(); onArchive(n.id); }}
          aria-label={`Archive: ${n.title}`} title="Archive"
        >
          ▢
        </button>
        <button
          type="button" className="g-notif-item__op"
          onClick={e => { e.stopPropagation(); onRemove(n.id); }}
          aria-label={`Delete: ${n.title}`} title="Delete"
        >
          ×
        </button>
      </div>
    </div>
  );
}

export const NotificationItem = memo(NotificationItemImpl);
