import { useCallback } from "react";
import type { FeedItem, FeedItemState } from "../types/feed.types";
import { FeedActionPanel } from "./FeedActionPanel";
import { FeedBottomOverlay } from "./FeedBottomOverlay";
import { useAppContext } from "../../../contexts/app";

interface FeedCardProps {
  item: FeedItem;
  state: FeedItemState;
  isActive: boolean;
  onLike: () => void;
  onSave: () => void;
}

export function FeedCard({ item, state, isActive, onLike, onSave }: FeedCardProps) {
  const { setPage } = useAppContext();

  /** Navigate to the target builder page (Phase 1). */
  const handleBuild = useCallback(() => {
    setPage(item.targetPage);
    /*
     * Phase 2 hook:
     * If item.sourceId is set, we'll want to pass it to the target page
     * so it auto-loads the template/project. For now, navigation alone is
     * sufficient and the data model already carries sourceId + sourceMeta.
     */
  }, [item.targetPage, setPage]);

  const handleShare = useCallback(() => {
    try {
      navigator.clipboard.writeText(`https://flow.app/feed/${item.id}`);
    } catch {
      /* Clipboard API unavailable (e.g. in non-secure context) — silently ignore */
    }
  }, [item.id]);

  const handleComment = useCallback(() => {
    /* Phase 2: open comments drawer */
  }, []);

  /* ── Background media rendering ─────────────────────────────── */
  let bgStyle: React.CSSProperties = {};
  if (item.media.type === "gradient") {
    bgStyle = { background: item.media.gradient };
  } else if (item.media.type === "image" && item.media.src) {
    bgStyle = {
      backgroundImage: `url(${item.media.src})`,
      backgroundSize: "cover",
      backgroundPosition: "center",
    };
  }
  /* video: Phase 2 — poster shown, <video> element added later */

  return (
    <article
      className={`feed-card${isActive ? " feed-card--active" : ""}`}
      aria-current={isActive}
    >
      {/* Background */}
      <div className="feed-card__bg" style={bgStyle} aria-hidden />

      {/* Cinematic dark vignette over the gradient */}
      <div className="feed-card__vignette" aria-hidden />

      {/* Action rail — fixed to the inline-end side (RTL-aware) */}
      <FeedActionPanel
        item={item}
        state={state}
        onLike={onLike}
        onSave={onSave}
        onShare={handleShare}
        onComment={handleComment}
        onBuild={handleBuild}
      />

      {/* Bottom info overlay */}
      <FeedBottomOverlay item={item} onBuild={handleBuild} />
    </article>
  );
}
