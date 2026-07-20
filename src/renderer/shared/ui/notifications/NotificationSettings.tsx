import { Dialog } from "../gold";
import { NOTIFICATION_CATEGORIES, useNotifications } from "../../../contexts/notifications";

const CATEGORY_LABEL: Record<string, string> = {
  system: "System", workflow: "Workflows", agent: "Agents", marketplace: "Marketplace",
  billing: "Billing", security: "Security", deployment: "Deployments",
  background_job: "Background jobs", realtime_event: "Realtime events", organization: "Organization",
};

export function NotificationSettings({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { mutedCategories, setMuted } = useNotifications();

  return (
    <Dialog open={open} onClose={onClose} title="Notification settings" width={380}>
      <p style={{ fontSize: 12.5, color: "var(--t5)", margin: "0 0 14px" }}>
        Turn off categories you don't want to be notified about. You can still see them in Activity.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NOTIFICATION_CATEGORIES.map(cat => {
          const muted = mutedCategories.includes(cat);
          return (
            <label key={cat} className="g-checkbox-row" style={{ justifyContent: "space-between", padding: "7px 2px" }}>
              <span>{CATEGORY_LABEL[cat] ?? cat}</span>
              <input
                type="checkbox"
                checked={!muted}
                onChange={e => setMuted(cat, !e.target.checked)}
                aria-label={`Notify me about ${CATEGORY_LABEL[cat] ?? cat}`}
              />
            </label>
          );
        })}
      </div>
    </Dialog>
  );
}
