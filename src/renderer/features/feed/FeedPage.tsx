import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { FeedTopBar } from "./components/FeedTopBar";
import { FeedCard } from "./components/FeedCard";
import { useFeedNavigation } from "./hooks/useFeedNavigation";
import { MOCK_FEED } from "./mock/feedData";
import { loadFeedItems, toggleLike as toggleLikeAPI, toggleSave as toggleSaveAPI } from "./services/feedService";
import type { FeedTab, FeedItem, FeedItemState } from "./types/feed.types";
import "./FeedPage.css";

/** Build the initial local interaction state from an item array */
function initStates(items: FeedItem[]): Record<string, FeedItemState> {
  return Object.fromEntries(
    items.map(item => [
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
  const [items, setItems]       = useState<FeedItem[]>(MOCK_FEED);
  const [isMock, setIsMock]     = useState(true);
  const [loading, setLoading]   = useState(true);
  const [feedError, setFeedError] = useState(false);
  const [states, setStates]     = useState<Record<string, FeedItemState>>(() => initStates(MOCK_FEED));

  useEffect(() => {
    let cancelled = false;
    loadFeedItems()
      .then(({ items: loaded, isMock: mock, error: err }) => {
        if (cancelled) return;
        setItems(loaded);
        setStates(initStates(loaded));
        setIsMock(mock);
        setFeedError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const { activeIndex, containerRef } = useFeedNavigation({ total: items.length });

  /* ── Interaction handlers ──────────────────────────────────── */
  const toggleLike = useCallback((id: string) => {
    let prev: FeedItemState | undefined;
    setStates(s => {
      prev = s[id];
      if (!prev) return s;
      return { ...s, [id]: { ...prev, liked: !prev.liked, likes: prev.liked ? prev.likes - 1 : prev.likes + 1 } };
    });
    toggleLikeAPI(id)
      .then(res => setStates(s => ({ ...s, [id]: { ...s[id], liked: res.liked, likes: res.count } })))
      .catch(() => setStates(s => prev ? { ...s, [id]: prev } : s));
  }, []);

  const toggleSave = useCallback((id: string) => {
    let prev: FeedItemState | undefined;
    setStates(s => {
      prev = s[id];
      if (!prev) return s;
      return { ...s, [id]: { ...prev, saved: !prev.saved, saves: prev.saved ? prev.saves - 1 : prev.saves + 1 } };
    });
    toggleSaveAPI(id)
      .then(res => setStates(s => ({ ...s, [id]: { ...s[id], saved: res.saved, saves: res.count } })))
      .catch(() => setStates(s => prev ? { ...s, [id]: prev } : s));
  }, []);

  /* ── Navigation indicator ──────────────────────────────────── */
  const total = items.length;
  const progressPct = total > 1 ? (activeIndex / (total - 1)) * 100 : 0;

  return (
    <div className="feed-page" role="main" aria-label={t("page.ariaLabel")}>
      {/* Top bar overlays the first card */}
      <FeedTopBar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Thin progress bar */}
      <div className="feed-progress" aria-hidden>
        <div className="feed-progress__bar" style={{ width: `${progressPct}%` }} />
      </div>

      {/* Loading overlay — shows MOCK_FEED cards underneath while real data loads */}
      {loading && (
        <div className="feed-loading" aria-live="polite" aria-label="Loading feed…" />
      )}

      {/* Error state */}
      {!loading && feedError && (
        <div className="feed-state feed-state--error" role="alert">
          <p className="feed-state__title">{t("error.title")}</p>
        </div>
      )}

      {/* Empty real feed */}
      {!loading && !feedError && items.length === 0 && (
        <div className="feed-state feed-state--empty" role="status">
          <p className="feed-state__title">{t("empty.title")}</p>
          <p className="feed-state__subtitle">{t("empty.subtitle")}</p>
        </div>
      )}

      {/* Scrollable card stack — only when there are items */}
      {items.length > 0 && (
        <div
          ref={containerRef}
          className="feed-scroll"
          aria-label={t("page.feedLabel")}
        >
          {items.map((item, idx) => (
            <FeedCard
              key={item.id}
              item={item}
              state={states[item.id] ?? { liked: false, saved: false, likes: 0, saves: 0 }}
              isActive={idx === activeIndex}
              isMock={isMock}
              onLike={() => toggleLike(item.id)}
              onSave={() => toggleSave(item.id)}
            />
          ))}
        </div>
      )}

      {/* Dot indicator */}
      {items.length > 0 && (
        <div className="feed-dots" aria-hidden>
          {items.map((item, idx) => (
            <span
              key={item.id}
              className={`feed-dot${idx === activeIndex ? " feed-dot--active" : ""}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
