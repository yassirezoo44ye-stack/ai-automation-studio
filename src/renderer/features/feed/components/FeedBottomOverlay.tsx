import { useTranslation } from "react-i18next";
import type { FeedItem } from "../types/feed.types";

/** Map ctaType → i18n key in feed.json `cta.*` namespace */
const CTA_I18N_KEY: Record<string, string> = {
  "build-app":      "cta.buildApp",
  "use-automation": "cta.useAutomation",
  "build-agent":    "cta.buildAgent",
  "run-workflow":   "cta.runWorkflow",
  "use-template":   "cta.useTemplate",
  "open-design":    "cta.openDesign",
};

/** Badge colour per content type */
const TYPE_COLORS: Record<string, string> = {
  APP:        "#3b82f6",
  AUTOMATION: "#10b981",
  AGENT:      "#8b5cf6",
  WORKFLOW:   "#f59e0b",
  TEMPLATE:   "#ec4899",
  DESIGN:     "#a855f7",
};

/** Localised type label */
function typeLabel(type: string, t: (k: string) => string): string {
  try { return t(`types.${type.toLowerCase()}`); } catch { return type; }
}

interface FeedBottomOverlayProps {
  item: FeedItem;
  onBuild: () => void;
}

export function FeedBottomOverlay({ item, onBuild }: FeedBottomOverlayProps) {
  const { t } = useTranslation("feed");
  const ctaText = t(CTA_I18N_KEY[item.ctaType] ?? "actions.build");

  return (
    <div className="feed-bottom-overlay">
      {/* Creator row */}
      <div className="feed-bottom-overlay__creator">
        <span className="feed-bottom-overlay__handle">{item.creator.handle}</span>
        <span
          className="feed-bottom-overlay__type-badge"
          style={{ background: TYPE_COLORS[item.type] ?? "var(--accent)" }}
        >
          {typeLabel(item.type, t)}
        </span>
      </div>

      {/* Title */}
      <h2 className="feed-bottom-overlay__title">{item.title}</h2>

      {/* Description */}
      <p className="feed-bottom-overlay__desc">{item.description}</p>

      {/* Tags */}
      <div className="feed-bottom-overlay__tags" aria-label={t("card.tags")}>
        {item.tags.map(tag => (
          <span key={tag} className="feed-bottom-overlay__tag">
            #{tag}
          </span>
        ))}
      </div>

      {/* Primary CTA */}
      <button
        className="feed-cta-btn"
        onClick={onBuild}
        aria-label={ctaText}
      >
        <span className="feed-cta-btn__icon">⚡</span>
        {ctaText}
      </button>
    </div>
  );
}
