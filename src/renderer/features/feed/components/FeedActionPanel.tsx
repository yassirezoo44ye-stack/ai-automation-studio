import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { FeedItem, FeedItemState } from "../types/feed.types";

function fmtNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}

interface FeedActionPanelProps {
  item: FeedItem;
  state: FeedItemState;
  onLike: () => void;
  onSave: () => void;
  onShare: () => void;
  onComment: () => void;
  onBuild: () => void;
}

/* ── Individual action button ─────────────────────────────────────── */
function ActionBtn({
  icon,
  label,
  count,
  active,
  onClick,
  activeColor = "var(--accent)",
}: {
  icon: React.ReactNode;
  label: string;
  count?: number;
  active?: boolean;
  onClick: () => void;
  activeColor?: string;
}) {
  return (
    <button
      className="feed-action-btn"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      style={{ color: active ? activeColor : undefined }}
    >
      <span className="feed-action-btn__icon">{icon}</span>
      {count !== undefined && (
        <span className="feed-action-btn__count">{fmtNum(count)}</span>
      )}
    </button>
  );
}

/* ── Icons (inline SVG — no deps) ────────────────────────────────── */
function HeartIcon({ filled }: { filled: boolean }) {
  return filled ? (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor">
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
    </svg>
  ) : (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
    </svg>
  );
}

function CommentIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
  );
}

function ShareIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
    </svg>
  );
}

function BookmarkIcon({ filled }: { filled: boolean }) {
  return filled ? (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
    </svg>
  ) : (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
    </svg>
  );
}

function BoltIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
    </svg>
  );
}

/* ── Creator avatar ───────────────────────────────────────────────── */
function CreatorAvatar({ creator }: { creator: FeedItem["creator"] }) {
  if (creator.avatar) {
    return (
      <div className="feed-action-avatar">
        <img src={creator.avatar} alt={creator.name} />
        <span className="feed-action-avatar__follow">+</span>
      </div>
    );
  }
  // initials fallback
  const initials = creator.name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div className="feed-action-avatar">
      <span className="feed-action-avatar__initials">{initials}</span>
      <span className="feed-action-avatar__follow">+</span>
    </div>
  );
}

/* ── Main component ───────────────────────────────────────────────── */
export function FeedActionPanel({ item, state, onLike, onSave, onShare, onComment, onBuild }: FeedActionPanelProps) {
  const { t } = useTranslation("feed");
  const [shareFlash, setShareFlash] = useState(false);

  function handleShare() {
    onShare();
    setShareFlash(true);
    setTimeout(() => setShareFlash(false), 1200);
  }

  return (
    <aside className="feed-action-rail" aria-label={t("actions.panelLabel")}>
      {/* Creator avatar at top of rail */}
      <CreatorAvatar creator={item.creator} />

      <ActionBtn
        icon={<HeartIcon filled={state.liked} />}
        label={t("actions.like")}
        count={state.likes}
        active={state.liked}
        activeColor="#ff2d55"
        onClick={onLike}
      />

      <ActionBtn
        icon={<CommentIcon />}
        label={t("actions.comment")}
        count={item.comments}
        onClick={onComment}
      />

      <ActionBtn
        icon={<ShareIcon />}
        label={shareFlash ? t("actions.copied") : t("actions.share")}
        count={item.shares}
        active={shareFlash}
        onClick={handleShare}
      />

      <ActionBtn
        icon={<BookmarkIcon filled={state.saved} />}
        label={t("actions.save")}
        count={state.saves}
        active={state.saved}
        activeColor="#fbbf24"
        onClick={onSave}
      />

      {/* Build CTA on rail */}
      <button
        className="feed-action-btn feed-action-btn--build"
        onClick={onBuild}
        aria-label={t("actions.build")}
        title={t("actions.build")}
      >
        <span className="feed-action-btn__icon"><BoltIcon /></span>
      </button>
    </aside>
  );
}
