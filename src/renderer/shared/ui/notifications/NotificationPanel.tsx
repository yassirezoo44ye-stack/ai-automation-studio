import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { createPortal } from "react-dom";
import { useOrg } from "../../../contexts/OrgContext";
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
  "careers", "study-library",
]);

export function NotificationPanel({ onClose, triggerRef }: {
  onClose: () => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}) {
  const { t } = useTranslation("common");
  const {
    notifications, status, error, hasMore, loadingMore, connectionStatus,
    filters, setFilters, refetch, loadMore, markRead, markAllRead, archive, remove,
  } = useNotifications();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const organization = useOrg({ optional: true });
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const [focusedIdx, setFocusedIdx] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const settingsTriggerRef = useRef<HTMLButtonElement>(null);
  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    settingsTriggerRef.current?.focus();
  }, []);
  const itemRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [position, setPosition] = useState<CSSProperties>({ top: 56, right: 12 });

  useLayoutEffect(() => {
    const place = () => {
      const anchor = triggerRef.current?.getBoundingClientRect();
      if (!anchor) return;
      const width = Math.min(340, window.innerWidth - 16);
      const below = window.innerHeight - anchor.bottom - 16;
      const above = anchor.top - 16;
      const down = below >= Math.min(320, above);
      const left = document.documentElement.dir === "rtl" ? anchor.left : anchor.right - width;
      setPosition({ width, left: Math.max(8, Math.min(left, window.innerWidth - width - 8)),
        ...(down ? { top: anchor.bottom + 8 } : { bottom: window.innerHeight - anchor.top + 8 }),
        maxHeight: Math.max(80, Math.min(480, down ? below : above)),
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [triggerRef]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      // Settings is a separate portal. Clicking inside it must not unmount
      // this panel (and therefore the settings dialog) underneath the user.
      if (settingsOpen) return;
      if (panelRef.current?.contains(e.target as Node)) return;
      if (triggerRef.current?.contains(e.target as Node)) return;
      onClose();
    }
    function onKey(e: globalThis.KeyboardEvent) {
      if (settingsOpen) return;
      if (e.key === "Escape") { onClose(); triggerRef.current?.focus(); }
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose, triggerRef, settingsOpen]);

  const handleNavigate = useCallback((href: string, organizationId?: string | null) => {
    if (typeof href !== "string") return;
    let target: URL;
    try { target = new URL(href, window.location.origin); } catch { return; }
    if (target.origin !== window.location.origin) return;
    const page = target.pathname.replace(/^\//, "").split("/")[0] || "home";
    const project = /^\/project\/[^/]+\/(build|design|automation|runs|integrations)$/.test(target.pathname);
    const flat = target.pathname === `/${page}` || target.pathname === "/";
    const feed = page === "feed" && /^\/feed\/[^/]+$/.test(target.pathname);
    if (!project && !(VALID_PAGES.has(page as Page) && (flat || feed))) return;
    if (organizationId && organization) {
      if (!organization.orgs.some(org => org.id === organizationId)) {
        setNavigationError(t("notifications.organizationUnavailable"));
        return;
      }
      organization.setCurrentOrgId(organizationId);
    }
    // AppContext consumes popstate. Preserve the notification's query string
    // and project route instead of dropping them during a flat page switch.
    window.history.pushState(null, "", target.pathname + target.search + target.hash);
    window.dispatchEvent(new PopStateEvent("popstate"));
    onClose();
  }, [onClose, organization, t]);

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

  return createPortal(
    <div ref={panelRef} style={position} className="g-notif-panel" role="dialog" aria-label={t("notifications.title")}>
      <div className="g-notif-panel__header">
        <span className="g-notif-panel__title">
          {t("notifications.title")}
          <span className={`g-notif-status g-notif-status--${connectionStatus}`} title={t(`notifications.statuses.${connectionStatus}`)} />
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" className="g-notif-item__op" onClick={markAllRead} title={t("notifications.markAllRead")} aria-label={t("notifications.markAllRead")}>✓✓</button>
          <button ref={settingsTriggerRef} type="button" className="g-notif-item__op" onClick={() => setSettingsOpen(true)} title={t("notifications.settings")} aria-label={t("notifications.settings")}>⚙</button>
        </div>
      </div>

      {status === "success" && error && <ErrorState compact message={error} onRetry={refetch} />}
      {navigationError && <ErrorState compact message={navigationError} onRetry={() => {
        void organization?.refreshOrgs().then(() => setNavigationError(null));
      }} />}

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
          aria-label={t("notifications.filterCategory")}
          className="g-notif-category-select"
        >
          <option value="">{t("notifications.allCategories")}</option>
          {Object.entries(t("notifications.categories", { returnObjects: true }) as Record<string, string>).map(([id, label]) => (
            <option key={id} value={id}>{label}</option>
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
        {status === "error" && <ErrorState compact message={error ?? "Failed to load."} onRetry={refetch} />}
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

      <NotificationSettings open={settingsOpen} onClose={closeSettings} />
    </div>, document.body,
  );
}
