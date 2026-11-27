import { useTranslation } from "react-i18next";
import type { FeedTab } from "../types/feed.types";

interface FeedTopBarProps {
  activeTab: FeedTab;
  onTabChange: (tab: FeedTab) => void;
}

const TABS: { id: FeedTab; enKey: string }[] = [
  { id: "for-you",   enKey: "forYou"   },
  { id: "following", enKey: "following" },
  { id: "explore",   enKey: "explore"  },
];

export function FeedTopBar({ activeTab, onTabChange }: FeedTopBarProps) {
  const { t } = useTranslation("feed");

  return (
    <div className="feed-topbar">
      {/* Flow logo mark */}
      <span className="feed-topbar__logo" aria-hidden>
        ⚡
      </span>

      {/* Tab pills. "Explore" opens another page, so it is a plain button
          beside the tablist rather than a tab inside it (WCAG 4.1.2). */}
      <div className="feed-topbar__tabs">
        <div role="tablist" aria-label={t("topBar.ariaLabel")} style={{ display: "flex", alignItems: "center" }}>
          {TABS.filter(tab => tab.id !== "explore").map(tab => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              disabled={tab.id === "following"}
              title={tab.id === "following" ? t("topBar.followingUnavailable") : undefined}
              className={`feed-topbar__tab${activeTab === tab.id ? " feed-topbar__tab--active" : ""}`}
              onClick={() => onTabChange(tab.id)}
            >
              {t(`topBar.${tab.enKey}`)}
            </button>
          ))}
        </div>
        <button
          type="button"
          className={`feed-topbar__tab${activeTab === "explore" ? " feed-topbar__tab--active" : ""}`}
          onClick={() => onTabChange("explore")}
        >
          {t("topBar.explore")}
        </button>
      </div>
    </div>
  );
}
