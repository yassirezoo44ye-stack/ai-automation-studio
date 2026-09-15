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
    <div className="feed-topbar" role="tablist" aria-label={t("topBar.ariaLabel")}>
      {/* Flow logo mark */}
      <span className="feed-topbar__logo" aria-hidden>
        ⚡
      </span>

      {/* Tab pills */}
      <div className="feed-topbar__tabs">
        {TABS.map(tab => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`feed-topbar__tab${activeTab === tab.id ? " feed-topbar__tab--active" : ""}`}
            onClick={() => onTabChange(tab.id)}
          >
            {t(`topBar.${tab.enKey}`)}
          </button>
        ))}
      </div>
    </div>
  );
}
