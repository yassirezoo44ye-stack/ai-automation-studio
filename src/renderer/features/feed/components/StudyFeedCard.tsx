import { useState } from "react";
import { useTranslation } from "react-i18next";
import { SecondaryActions } from "../../../shared/ui/SecondaryActions";
import type { FeedItem } from "../types/feed.types";

export function StudyFeedCard({ item, isActive }: { item: FeedItem; isActive: boolean }) {
  const { t } = useTranslation("feed");
  const [coverFailed, setCoverFailed] = useState(false);
  const [shareState, setShareState] = useState<"idle" | "copied" | "shared" | "manual">("idle");
  const [sharing, setSharing] = useState(false);
  const href = `/study-library?lesson=${encodeURIComponent(item.sourceId ?? "")}`;
  const subject = item.tags.find(tag => ["math", "physics", "chemistry", "biology", "english", "computing"].includes(tag));
  const shareUrl = new URL(href, window.location.origin).href;

  async function share() {
    setSharing(true); setShareState("idle");
    try {
      if (navigator.share) {
        try {
          await navigator.share({ title: item.title, url: shareUrl });
          setShareState("shared"); return;
        } catch (error) {
          if (typeof error === "object" && error !== null && "name" in error && error.name === "AbortError") return;
        }
      }
      if (navigator.clipboard?.writeText) {
        try { await navigator.clipboard.writeText(shareUrl); setShareState("copied"); return; }
        catch { /* Keep the public link available for manual copying. */ }
      }
      setShareState("manual");
    } finally { setSharing(false); }
  }

  return <article className={`feed-card feed-study-card${isActive ? " feed-card--active" : ""}`} aria-current={isActive}>
    {!coverFailed && item.media.src ? <img className="feed-study-cover" src={item.media.src} alt={item.title} loading="lazy" onError={() => setCoverFailed(true)} />
      : <div className="feed-study-cover-fallback" role="img" aria-label={t("study.coverUnavailable")}><span aria-hidden="true">✦</span></div>}
    <div className="feed-card__vignette" aria-hidden />
    <div className="feed-bottom-overlay">
      <span className="feed-bottom-overlay__type-badge">{t("study.label")}</span>
      <h2 className="feed-bottom-overlay__title" dir="auto">{item.title}</h2>
      <p className="feed-bottom-overlay__desc" dir="auto">{item.description}</p>
      <p>{t("study.access")}</p>
      <a className="feed-cta-btn" href={href}>{t("study.open")}</a>
      <SecondaryActions label={t("study.more")}>
        <button type="button" disabled={sharing} onClick={() => void share()}>{t(sharing ? "study.sharing" : "actions.share")}</button>
        {subject && <a href={`/study-library?subject=${encodeURIComponent(subject)}`}>{t("study.related", { subject: t(`study.subjects.${subject}`) })}</a>}
        {shareState !== "idle" && <p role="status">{t(`study.${shareState}`)}</p>}
        {shareState === "manual" && <label>{t("study.copyLink")}<input readOnly value={shareUrl} onFocus={event => event.currentTarget.select()} /></label>}
      </SecondaryActions>
    </div>
  </article>;
}
