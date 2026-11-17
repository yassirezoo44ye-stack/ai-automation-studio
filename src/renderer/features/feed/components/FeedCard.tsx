import { useCallback, useState, useRef, useEffect } from "react";
import type { FeedItem, FeedItemState } from "../types/feed.types";
import { FeedActionPanel } from "./FeedActionPanel";
import { FeedBottomOverlay } from "./FeedBottomOverlay";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../../contexts/app";

interface FeedCardProps {
  item: FeedItem;
  state: FeedItemState;
  isActive: boolean;
  isMock?: boolean;
  onLike: () => void;
  onSave: () => void;
}

export function FeedCard({ item, state, isActive, isMock = false, onLike, onSave }: FeedCardProps) {
  const { setPage, setFeedIntent } = useAppContext();
  const { t } = useTranslation("feed");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!detailsOpen) return;
    if (detailsRef.current?.showModal) detailsRef.current.showModal();
    else detailsRef.current?.setAttribute("open", "");
  }, [detailsOpen]);

  const handleBuild = useCallback(() => {
    if (item.ctaType === "view-creation") { setDetailsOpen(true); return; }
    setFeedIntent({
      sourceId:    item.sourceId,
      sourceType:  item.sourceType,
      sourceMeta:  item.sourceMeta,
      originItemId: item.id,
    });
    setPage(item.targetPage);
  }, [item.ctaType, item.id, item.sourceId, item.sourceType, item.sourceMeta, item.targetPage, setPage, setFeedIntent]);

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
        isMock={isMock}
        onLike={onLike}
        onSave={onSave}
        onShare={handleShare}
        onComment={handleComment}
        onBuild={handleBuild}
      />

      {/* Bottom info overlay */}
      <FeedBottomOverlay item={item} onBuild={handleBuild} />
      {detailsOpen && <dialog ref={detailsRef} className="feed-real-details" aria-label={t("realFeed.view")} onCancel={() => setDetailsOpen(false)}>
        <h2>{item.title}</h2><p>{item.description}</p>
        <p>{t("realFeed.publisher")}: {item.creator.name || t("realFeed.unnamed")}</p>
        {typeof item.sourceMeta?.createdAt === "string" && <time dateTime={item.sourceMeta.createdAt}>{new Date(item.sourceMeta.createdAt).toLocaleDateString()}</time>}
        <p>{t("realFeed.scope")}</p>
        <button onClick={() => setDetailsOpen(false)}>{t("realFeed.close")}</button>
      </dialog>}
    </article>
  );
}
