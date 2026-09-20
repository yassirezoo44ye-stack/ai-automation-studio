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
  const { setPage, setFeedIntent } = useAppContext();

  const handleBuild = useCallback(() => {
    setFeedIntent({
      sourceId:    item.sourceId,
      sourceType:  item.sourceType,
      sourceMeta:  item.sourceMeta,
      originItemId: item.id,
    });
    setPage(item.targetPage);
  }, [item.id, item.sourceId, item.sourceType, item.sourceMeta, item.targetPage, setPage, setFeedIntent]);

  const handleShare = useCallback(async (): Promise<boolean> => {
    const url = `${window.location.origin}/feed/${item.id}`;

    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(url);
        return true;
      } catch {
        /* insecure context or permission denied — fall through */
      }
    }

    if (navigator.share) {
      try {
        await navigator.share({ url });
        return true;
      } catch {
        return false; // user cancelled
      }
    }

    window.prompt("Copy this link:", url);
    return false;
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
