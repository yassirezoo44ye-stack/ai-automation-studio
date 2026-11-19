import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../../contexts/app";
import { useNotifications, type NotificationCategory } from "../../../contexts/notifications";
import { LoadingSpinner } from "../LoadingSpinner";
import { ErrorState } from "../StateViews";
import { GoldButton } from "../gold";
import { NotificationItem } from "./NotificationItem";
import { EmptyNotifications } from "./EmptyNotifications";
import { NotificationSettings } from "./NotificationSettings";
import type { Page } from "../../types";

const VALID_PAGES = new Set<Page>([
  "home", "ai", "dev", "design", "automation", "social", "settings", "agentos",
  "marketplace", "organizations", "teams", "billing", "plugins", "sandbox",
  "ai-routing", "observability", "app-builder", "runs", "integrations", "training",
  "business-lab", "devices", "discover", "feed", "leads", "saas-factory", "new-project",
]);

const CATEGORY_IDS = [
  "system", "workflow", "agent", "marketplace", "billing", "security", "deployment",
  "background_job", "realtime_event", "organization",
] as const;

export function NotificationPanel({ onClose, triggerRef }: {
  onClose: () => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}) {
  const {
    notifications, status, error, hasMore, loadingMore, connectionStatus,
    filters, setFilters, refetch, loadMore, markRead, markAllRead, archive, remove,
  } = useNotifications();
  const { setPage } = useAppContext();
  const { t } = useTranslation("common");

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [focusedIdx, setFocusedIdx] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (panelRef.current?.contains(e.target as Node)) return;
      if (triggerRef.current?.contains(e.target as Node)) return;
      onClose();
    }
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") { onClose(); triggerRef.current?.focus(); }
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose, triggerRef]);

  const handleNavigate = useCallback((href: string) => {
    // Every in-app destination is a Page id (see notifications/templates.py
    // actions) — this app has no router, navigation is AppContext.setPage.
    const page = href.replace(/^\//, "").split("?")[0].split("/")[0];
    if (VALID_PAGES.has(page as Page)) setPage(page as Page);
    onClose();
  }, [setPage, onClose]);

  function onListKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (notifications.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusedIdx(i => {
        const next = Math.min(i + 1, notifications.length - 1);
        itemRefs.current[next]?.focus();
        return next;
      });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusedIdx(i => {
        const next = Math.max(i - 1, 0);
        itemRefs.current[next]?.focus();
        return next;
      });
    }
  }

  return (
    <div ref={panelRef} className="g-notif-panel" role="dialog" aria-label={t("notifications.title")}>
      <div className="g-notif-panel__header">
        <span className="g-notif-panel__title">
          {t("notifications.title")}
          <span className={`g-notif-status g-notif-status--${connectionStatus}`} role="img" title={t(`notifications.status.${connectionStatus}`)} aria-label={t(`notifications.status.${connectionStatus}`)} />
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" className="g-notif-item__op" onClick={markAllRead} title={t("notifications.markAllRead")} aria-label={t("notifications.markAllRead")}>✓✓</button>
          <button type="button" className="g-notif-item__op" onClick={() => setSettingsOpen(true)} title={t("notifications.settingsShort")} aria-label={t("notifications.settings")}>⚙</button>
        </div>
      </div>

      <div className="g-notif-panel__filters">
        <button
          type="button"
          className={`g-notif-chip ${!filters.unreadOnly ? "g-notif-chip--active" : ""}`}
          onClick={() => setFilters({ unreadOnly: false })}
        >{t("notifications.all")}</button>
        <button
          type="button"
          className={`g-notif-chip ${filters.unreadOnly ? "g-notif-chip--active" : ""}`}
          onClick={() => setFilters({ unreadOnly: true })}
        >{t("notifications.unread")}</button>
        <select
          value={filters.category ?? ""}
          onChange={e => setFilters({ category: (e.target.value || null) as NotificationCategory | null })}
          aria-label={t("notifications.filterByCategory")}
          className="g-notif-category-select"
        >
          <option value="">{t("notifications.allCategories")}</option>
          {CATEGORY_IDS.map(id => (
            <option key={id} value={id}>{t(`notifications.category.${id}`)}</option>
          ))}
        </select>
      </div>

      <div
        className="g-notif-panel__list"
        role="listbox"
        aria-label={t("notifications.list")}
        onKeyDown={onListKeyDown}
        tabIndex={-1}
      >
        {status === "loading" && <LoadingSpinner label={t("notifications.loading")} />}
        {status === "error" && <ErrorState compact message={error ?? t("notifications.loadFailed")} onRetry={refetch} />}
        {status === "success" && notifications.length === 0 && (
          <EmptyNotifications filtered={filters.unreadOnly || !!filters.category} />
        )}
        {status === "success" && notifications.map((n, i) => (
          <NotificationItem
            key={n.id}
            notification={n}
            focused={i === focusedIdx}
            onSelect={markRead}
            onArchive={archive}
            onRemove={remove}
            onNavigate={handleNavigate}
            itemRef={el => { itemRefs.current[i] = el; }}
          />
        ))}
        {status === "success" && hasMore && (
          <div style={{ padding: "8px 12px" }}>
            <GoldButton variant="ghost" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? t("notifications.loadingMore") : t("notifications.loadMore")}
            </GoldButton>
          </div>
        )}
      </div>

      <NotificationSettings open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
