// Notification context + hook — split from NotificationContext.tsx so that
// file exports only its component (react-refresh/only-export-components),
// matching the app.ts / toast.ts convention.
import { createContext, useContext } from "react";

export type NotificationSeverity = "success" | "info" | "warning" | "error";
export type NotificationCategory =
  | "system" | "workflow" | "agent" | "marketplace" | "billing"
  | "security" | "deployment" | "background_job" | "realtime_event" | "organization";

export const NOTIFICATION_CATEGORIES: NotificationCategory[] = [
  "system", "workflow", "agent", "marketplace", "billing",
  "security", "deployment", "background_job", "realtime_event", "organization",
];

export interface NotificationActionLink { label: string; href: string }

export interface Notification {
  id: string;
  organization_id: string | null;
  type: string;
  category: NotificationCategory;
  severity: NotificationSeverity;
  title: string;
  message: string;
  source: string | null;
  action: NotificationActionLink | null;
  dismissible: boolean;
  read_status: boolean;
  read_at: string | null;
  archived_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export type ConnectionStatus = "connecting" | "live" | "reconnecting" | "offline";

export interface NotificationFilters {
  unreadOnly: boolean;
  category: NotificationCategory | null;
  search: string;
}

export interface NotificationContextType {
  notifications: Notification[];
  unreadCount: number;
  status: "loading" | "success" | "error";
  error: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  connectionStatus: ConnectionStatus;
  filters: NotificationFilters;
  setFilters: (f: Partial<NotificationFilters>) => void;
  mutedCategories: NotificationCategory[];
  refetch: () => void;
  loadMore: () => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  archive: (id: string) => void;
  remove: (id: string) => void;
  setMuted: (category: NotificationCategory, muted: boolean) => void;
}

const noop = () => {};

export const NotificationContext = createContext<NotificationContextType>({
  notifications: [],
  unreadCount: 0,
  status: "loading",
  error: null,
  hasMore: false,
  loadingMore: false,
  connectionStatus: "offline",
  filters: { unreadOnly: false, category: null, search: "" },
  setFilters: noop,
  mutedCategories: [],
  refetch: noop,
  loadMore: noop,
  markRead: noop,
  markAllRead: noop,
  archive: noop,
  remove: noop,
  setMuted: noop,
});

export function useNotifications(): NotificationContextType {
  return useContext(NotificationContext);
}
