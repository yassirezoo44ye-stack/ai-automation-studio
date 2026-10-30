import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { FeedTopBar } from "./components/FeedTopBar";
import { StudyFeedCard } from "./components/StudyFeedCard";
import { FeedCard } from "./components/FeedCard";
import { useFeedNavigation } from "./hooks/useFeedNavigation";
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
  const [contentFilter, setContentFilter] = useState<"all" | "study">("all");
  const [search, setSearch] = useState("");
  const [subject, setSubject] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [activeTab, setActiveTab] = useState<FeedTab>("for-you");
  const [items, setItems]       = useState<FeedItem[]>([]);
  const [isMock, setIsMock]     = useState(false);
  const [loading, setLoading]   = useState(true);
  const [feedError, setFeedError] = useState(false);
  const [states, setStates]     = useState<Record<string, FeedItemState>>({});

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
  }, [refresh]);

  const needle = search.trim().toLocaleLowerCase();
  const visibleItems = items.filter(item =>
    (contentFilter !== "study" || item.type === "STUDY") &&
    (!subject || (item.type === "STUDY" && item.tags.includes(subject))) &&
    (!needle || `${item.title} ${item.description}`.toLocaleLowerCase().includes(needle))
  );
  const { activeIndex, containerRef, scrollToIndex } = useFeedNavigation({ total: visibleItems.length });

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
  const total = visibleItems.length;
  const progressPct = total > 1 ? (activeIndex / (total - 1)) * 100 : 0;

  return (
    <div className="feed-page" role="main" aria-label={t("page.ariaLabel")}>
      {/* Top bar overlays the first card */}
      <FeedTopBar activeTab={activeTab} onTabChange={setActiveTab} />
      <div className="feed-content-filters" role="group" aria-label={t("study.filterLabel")}>
        {(["all", "study"] as const).map(filter => <button key={filter} aria-pressed={contentFilter === filter} onClick={() => { scrollToIndex(0); setContentFilter(filter); setSubject(""); }}>{t(`study.${filter}`)}</button>)}
        <label className="feed-search-label"><span>{t("study.search")}</span><input type="search" value={search} maxLength={120} placeholder={t("study.searchPlaceholder")} onChange={event => { scrollToIndex(0); setSearch(event.target.value); }} /></label>
        {contentFilter === "study" && <label><span className="feed-control-label">{t("study.subject")}</span><select aria-label={t("study.subject")} value={subject} onChange={event => { scrollToIndex(0); setSubject(event.target.value); }}>
          {["", "math", "physics", "chemistry", "biology", "english", "computing"].map(value => <option key={value} value={value}>{t(`study.subjects.${value || "all"}`)}</option>)}
        </select></label>}
      </div>

      {/* Thin progress bar */}
      <div className="feed-progress" aria-hidden>
        <div className="feed-progress__bar" style={{ width: `${progressPct}%` }} />
      </div>

      {/* Loading skeleton — items are empty during load so no mock cards show underneath */}
      {loading && (
        <div className="feed-loading" aria-live="polite" aria-label="Loading feed…" />
      )}

      {/* Error state */}
      {!loading && feedError && (
        <div className={items.length ? "feed-partial-error" : "feed-state feed-state--error"} role="alert">
          <p className="feed-state__title">{t(items.length ? "error.partial" : "error.title")}</p>
          <button onClick={() => { setLoading(true); setRefresh(value => value + 1); }}>{t("error.retry")}</button>
        </div>
      )}

      {/* Empty real feed */}
      {!loading && visibleItems.length === 0 && (!feedError || items.length > 0) && (
        <div className="feed-state feed-state--empty" role="status">
          <p className="feed-state__title">{t(search || subject ? "study.noMatches" : contentFilter === "study" ? "study.empty" : "empty.title")}</p>
          <p className="feed-state__subtitle">{t(search || subject ? "study.adjustFilters" : "empty.subtitle")}</p>
          {(search || subject) && <button onClick={() => { setSearch(""); setSubject(""); }}>{t("study.clear")}</button>}
        </div>
      )}

      {/* Scrollable card stack — only when there are items */}
      {visibleItems.length > 0 && (
        <div
          ref={containerRef}
          className="feed-scroll"
          aria-label={t("page.feedLabel")}
        >
          {visibleItems.map((item, idx) => item.type === "STUDY" ? (
            <StudyFeedCard key={item.id} item={item} isActive={idx === activeIndex} />
          ) : (
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
      {visibleItems.length > 0 && (
        <div className="feed-dots" aria-hidden>
          {visibleItems.map((item, idx) => (
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
