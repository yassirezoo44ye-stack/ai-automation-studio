import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { FeedTopBar } from "./components/FeedTopBar";
import { FeedCard } from "./components/FeedCard";
import { useFeedNavigation } from "./hooks/useFeedNavigation";
import { MOCK_FEED } from "./mock/feedData";
import type { FeedTab, FeedItemState } from "./types/feed.types";
import "./FeedPage.css";

/** Build the initial local interaction state from the mock seed values */
function initStates(): Record<string, FeedItemState> {
  return Object.fromEntries(
    MOCK_FEED.map(item => [
      item.id,
      {
        liked: item.userLiked ?? false,
        saved: item.userSaved ?? false,
        likes: item.likes,
        saves: item.saves,
      },
    ])
  );
}

export function FeedPage() {
  const { t } = useTranslation("feed");
  const [activeTab, setActiveTab] = useState<FeedTab>("for-you");
  const [states, setStates] = useState<Record<string, FeedItemState>>(initStates);

  const { activeIndex, containerRef } = useFeedNavigation({ total: MOCK_FEED.length });

  /* ── Interaction handlers ──────────────────────────────────── */
  const toggleLike = useCallback((id: string) => {
    setStates(prev => {
      const s = prev[id];
      return {
        ...prev,
        [id]: { ...s, liked: !s.liked, likes: s.liked ? s.likes - 1 : s.likes + 1 },
      };
    });
  }, []);

  const toggleSave = useCallback((id: string) => {
    setStates(prev => {
      const s = prev[id];
      return {
        ...prev,
        [id]: { ...s, saved: !s.saved, saves: s.saved ? s.saves - 1 : s.saves + 1 },
      };
    });
  }, []);

  /* ── Navigation indicator ──────────────────────────────────── */
  const total = MOCK_FEED.length;
  const progressPct = total > 1 ? (activeIndex / (total - 1)) * 100 : 0;

  return (
    <div className="feed-page" role="main" aria-label={t("page.ariaLabel")}>
      {/* Top bar overlays the first card */}
      <FeedTopBar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Thin progress bar */}
      <div className="feed-progress" aria-hidden>
        <div className="feed-progress__bar" style={{ width: `${progressPct}%` }} />
      </div>

      {/* Scrollable card stack */}
      <div
        ref={containerRef}
        className="feed-scroll"
        aria-label={t("page.feedLabel")}
        tabIndex={0}
      >
        {MOCK_FEED.map((item, idx) => (
          <FeedCard
            key={item.id}
            item={item}
            state={states[item.id]}
            isActive={idx === activeIndex}
            onLike={() => toggleLike(item.id)}
            onSave={() => toggleSave(item.id)}
          />
        ))}
      </div>

      {/* Dot indicator */}
      <div className="feed-dots" aria-hidden>
        {MOCK_FEED.map((item, idx) => (
          <span
            key={item.id}
            className={`feed-dot${idx === activeIndex ? " feed-dot--active" : ""}`}
          />
        ))}
      </div>
    </div>
  );
}
