import { EmptyState } from "../StateViews";

export function EmptyNotifications({ filtered = false }: { filtered?: boolean }) {
  return (
    <EmptyState
      compact
      icon={
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
      }
      title={filtered ? "No notifications match" : "You're all caught up"}
      description={filtered ? "Try clearing filters to see more." : "New activity will show up here."}
    />
  );
}
