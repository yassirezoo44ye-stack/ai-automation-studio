import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { FeedTopBar } from "./components/FeedTopBar";
import { FeedCard } from "./components/FeedCard";
import { useFeedNavigation } from "./hooks/useFeedNavigation";
import { loadFeedItems, toggleLike as toggleLikeAPI, toggleSave as toggleSaveAPI } from "./services/feedService";
import { useAppContext } from "../../contexts/app";
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
  const { setPage } = useAppContext();
  const [activeTab, setActiveTab] = useState<FeedTab>("for-you");
  const [items, setItems]     = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [states, setStates]   = useState<Record<string, FeedItemState>>({});
  // Bumped by the retry button to re-run the load effect
  const [loadAttempt, setLoadAttempt] = useState(0);

  // Real data only: no mock content is shown while loading, when the feed
  // is empty, or when the API fails.
  useEffect(() => {
    let cancelled = false;
    loadFeedItems()
      .then(({ items: loaded, error: loadError }) => {
        if (cancelled) return;
        setItems(loaded);
        setStates(initStates(loaded));
        setError(loadError);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [loadAttempt]);

  const retry = useCallback(() => {
    setLoading(true);
    setError(null);
    setLoadAttempt(n => n + 1);
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

  /* ── Loading / error / empty states (no mock fallback) ─────── */
  let status: React.ReactNode = null;
  if (loading) {
    status = (
      <div className="feed-status" role="status" aria-live="polite">
        <p className="feed-status__title">{t("status.loading")}</p>
      </div>
    );
  } else if (error) {
    status = (
      <div className="feed-status" role="alert">
        <p className="feed-status__title">{t("status.errorTitle")}</p>
        <p className="feed-status__body">{t("status.errorBody")}</p>
        <button className="feed-status__btn" onClick={retry}>{t("status.retry")}</button>
      </div>
    );
  } else if (total === 0) {
    status = (
      <div className="feed-status" role="status">
        <p className="feed-status__title">{t("status.emptyTitle")}</p>
        <p className="feed-status__body">{t("status.emptyBody")}</p>
        <button className="feed-status__btn" onClick={() => setPage("app-builder")}>
          {t("status.emptyCta")}
        </button>
      </div>
    );
  }

  return (
    <div className="feed-page" role="main" aria-label={t("page.ariaLabel")}>
      {/* Top bar overlays the first card */}
      <FeedTopBar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Thin progress bar */}
      <div className="feed-progress" aria-hidden>
        <div className="feed-progress__bar" style={{ width: `${progressPct}%` }} />
      </div>

      {status}

      {/* Scrollable card stack — always mounted so navigation listeners attach */}
      <div
        ref={containerRef}
        className="feed-scroll"
        aria-label={t("page.feedLabel")}
        tabIndex={0}
      >
        {!loading && items.map((item, idx) => (
          <FeedCard
            key={item.id}
            item={item}
            state={states[item.id] ?? { liked: false, saved: false, likes: 0, saves: 0 }}
            isActive={idx === activeIndex}
            onLike={() => toggleLike(item.id)}
            onSave={() => toggleSave(item.id)}
          />
        ))}
      </div>

      {/* Dot indicator */}
      <div className="feed-dots" aria-hidden>
        {!loading && items.map((item, idx) => (
          <span
            key={item.id}
            className={`feed-dot${idx === activeIndex ? " feed-dot--active" : ""}`}
          />
        ))}
      </div>
    </div>
  );
}
