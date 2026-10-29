import { useTranslation } from "react-i18next";
import type { FeedItem } from "../types/feed.types";

export function StudyFeedCard({ item, isActive }: { item: FeedItem; isActive: boolean }) {
  const { t } = useTranslation("feed");
  const href = `/study-library?lesson=${encodeURIComponent(item.sourceId ?? "")}`;
  return <article className={`feed-card feed-study-card${isActive ? " feed-card--active" : ""}`} aria-current={isActive}>
    <img className="feed-study-cover" src={item.media.src} alt={item.title} loading="lazy" />
    <div className="feed-card__vignette" aria-hidden />
    <div className="feed-bottom-overlay">
      <span className="feed-bottom-overlay__type-badge">{t("study.label")}</span>
      <h2 className="feed-bottom-overlay__title" dir="auto">{item.title}</h2>
      <p className="feed-bottom-overlay__desc" dir="auto">{item.description}</p>
      <p>{t("study.access")}</p>
      <a className="feed-cta-btn" href={href}>{t("study.open")}</a>
    </div>
  </article>;
}
