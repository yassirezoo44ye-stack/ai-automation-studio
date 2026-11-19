import { useTranslation } from "react-i18next";
import { ErrorState } from "../StateViews";
import { Dialog } from "../gold";
import { NOTIFICATION_CATEGORIES, useNotifications } from "../../../contexts/notifications";

export function NotificationSettings({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("common");
  const { mutedCategories, setMuted, error, refetch, preferencesLoaded = true, savingPreferences } = useNotifications();

  return (
    <Dialog open={open} onClose={onClose} title={t("notifications.settings")} width={380}>
      <p style={{ fontSize: 12.5, color: "var(--t5)", margin: "0 0 14px" }}>
        {t("notifications.instructions")}
      </p>
      {error && <ErrorState compact message={error} onRetry={refetch} />}
      {savingPreferences && <p role="status">{t("notifications.saving")}</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {NOTIFICATION_CATEGORIES.map(cat => {
          const muted = mutedCategories.includes(cat);
          return (
            <label key={cat} className="g-checkbox-row" style={{ justifyContent: "space-between", padding: "7px 2px" }}>
              <span>{t(`notifications.categories.${cat}`)}</span>
              <input
                type="checkbox"
                checked={!muted}
                disabled={!preferencesLoaded || savingPreferences}
                onChange={e => setMuted(cat, !e.target.checked)}
                aria-label={t("notifications.notifyCategory", { category: t(`notifications.categories.${cat}`) })}
              />
            </label>
          );
        })}
      </div>
    </Dialog>
  );
}
