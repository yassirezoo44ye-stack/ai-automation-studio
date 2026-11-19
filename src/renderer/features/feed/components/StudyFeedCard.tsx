import { useTranslation } from "react-i18next";
import type { FeedItem } from "../types/feed.types";
import { relativeDate } from "./relativeDate";

/** One colour per subject so a scroll through the feed reads at a glance. */
const SUBJECT_COLORS: Record<string, string> = {
  math: "#2563eb", physics: "#7c3aed", chemistry: "#0d9488",
  biology: "#16a34a", english: "#db2777", computing: "#ea580c",
};

export function StudyFeedCard({ item, isActive }: { item: FeedItem; isActive: boolean }) {
  const { t, i18n } = useTranslation("feed");
  const href = `/study-library?lesson=${encodeURIComponent(item.sourceId ?? "")}`;
  const subject = item.tags[0] ?? "";
  const subjectLabel = subject ? t(`study.subjects.${subject}`, { defaultValue: t("study.label") }) : t("study.label");
  const when = relativeDate(item.publishedAt, i18n?.language ?? "en");
  const meta = [
    item.pages ? t("study.pages", { count: item.pages }) : "",
    when,
  ].filter(Boolean).join(" · ");
  return <article className={`feed-card feed-study-card${isActive ? " feed-card--active" : ""}`} aria-current={isActive}>
    {/* Decorative: the title is read out just below. */}
    <img className="feed-study-cover" src={item.media.src} alt="" loading="lazy" />
    <div className="feed-card__vignette" aria-hidden />
    <div className="feed-bottom-overlay">
      <div className="feed-bottom-overlay__creator">
        <span className="feed-bottom-overlay__type-badge" style={{ background: SUBJECT_COLORS[subject] ?? "var(--accent)" }}>{subjectLabel}</span>
        {meta && <span className="feed-study-meta">{meta}</span>}
      </div>
      <h2 className="feed-bottom-overlay__title" dir="auto">{item.title}</h2>
      <p className="feed-bottom-overlay__desc" dir="auto">{item.description}</p>
      <a className="feed-cta-btn" href={href}>{t("study.open")}</a>
      <p className="feed-study-access">{t("study.access")}</p>
    </div>
  </article>;
}
