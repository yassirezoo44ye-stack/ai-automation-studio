/**
 * AIToolsSectionPanel
 *
 * Renders a curated catalogue of AI tools for a selected AppSection category.
 * Categories are extracted from the 6-slide AI-tools reference (slides 2–7):
 *
 *  2 — ai-assistants     : General AI Assistants  (ChatGPT / Claude / Perplexity)
 *  3 — no-code-dev       : No-Code Development    (Cursor / Lovable / Replit)
 *  4 — content-production: Content Production     (HeyGen / Synthesia / Descript)
 *  5 — productivity      : Productivity & Focus   (NotebookLM / Gamma / Granola)
 *  6 — creativity-design : Creativity & Design    (Kling / ElevenLabs / Google Veo)
 *  7 — automation-int    : Automation & Integration (n8n / Claude Code / Zapier)
 *
 * Starred (⭐) tools are the top recommended pick per category.
 */
import { useTranslation } from "react-i18next";
import type { AppSection } from "./AppTreePanel";

/* ── Types ────────────────────────────────────────────────────────────────── */

interface AiTool {
  name: string;
  /** Short functional role */
  role: string;
  /** Emoji used as a simple logo stand-in */
  emoji: string;
  /** Top-pick for this category */
  starred?: boolean;
  url: string;
}

interface CategoryMeta {
  section: AppSection;
  /** i18n key inside designStudio.aiToolsPanel.categories.<key> */
  key: string;
  tools: AiTool[];
  descKey: string;
  exampleKey: string;
}

/* ── Catalogue data ────────────────────────────────────────────────────────── */

const CATALOGUE: CategoryMeta[] = [
  {
    section:    "ai-assistants",
    key:        "aiAssistants",
    descKey:    "aiAssistantsDesc",
    exampleKey: "aiAssistantsExample",
    tools: [
      { name: "ChatGPT",    role: "Quick tasks & chat",        emoji: "🤖", url: "https://chatgpt.com" },
      { name: "Claude",     role: "Deep writing & reasoning",  emoji: "✦",  starred: true, url: "https://claude.ai" },
      { name: "Perplexity", role: "Real-time search + sources",emoji: "🔍", url: "https://perplexity.ai" },
    ],
  },
  {
    section:    "no-code-dev",
    key:        "noCodeDev",
    descKey:    "noCodeDevDesc",
    exampleKey: "noCodeDevExample",
    tools: [
      { name: "Cursor",  role: "AI-powered code editor",  emoji: "⬛", url: "https://cursor.sh" },
      { name: "Lovable", role: "Idea → app in 2 minutes", emoji: "❤️", starred: true, url: "https://lovable.dev" },
      { name: "Replit",  role: "Cloud IDE & deployment",  emoji: "🔲", url: "https://replit.com" },
    ],
  },
  {
    section:    "content-production",
    key:        "contentProduction",
    descKey:    "contentProductionDesc",
    exampleKey: "contentProductionExample",
    tools: [
      { name: "HeyGen",    role: "AI avatar videos",        emoji: "🎬", starred: true, url: "https://heygen.com" },
      { name: "Synthesia", role: "Text-to-video presenter", emoji: "🎥", url: "https://synthesia.io" },
      { name: "Descript",  role: "Video & podcast editing", emoji: "🎙️", url: "https://descript.com" },
    ],
  },
  {
    section:    "productivity",
    key:        "productivity",
    descKey:    "productivityDesc",
    exampleKey: "productivityExample",
    tools: [
      { name: "NotebookLM", role: "AI research assistant", emoji: "📓", starred: true, url: "https://notebooklm.google" },
      { name: "Gamma",      role: "AI presentations",      emoji: "⬡",  url: "https://gamma.app" },
      { name: "Granola",    role: "AI meeting notes",       emoji: "🌿", url: "https://granola.ai" },
    ],
  },
  {
    section:    "creativity-design",
    key:        "creativityDesign",
    descKey:    "creativityDesignDesc",
    exampleKey: "creativityDesignExample",
    tools: [
      { name: "Kling",       role: "AI video generation",    emoji: "🎞️", starred: true, url: "https://klingai.com" },
      { name: "ElevenLabs",  role: "Text-to-voice (Arabic)", emoji: "🔊", starred: true, url: "https://elevenlabs.io" },
      { name: "Google Veo",  role: "AI cinematic video",     emoji: "🎥", url: "https://deepmind.google/veo" },
    ],
  },
  {
    section:    "automation-int",
    key:        "automationInt",
    descKey:    "automationIntDesc",
    exampleKey: "automationIntExample",
    tools: [
      { name: "n8n",         role: "Visual workflow automation", emoji: "🔀", starred: true, url: "https://n8n.io" },
      { name: "Claude Code", role: "AI coding agent (CLI)",      emoji: "✦",  starred: true, url: "https://claude.ai/code" },
      { name: "Zapier",      role: "5 000+ app connectors",      emoji: "⚡", url: "https://zapier.com" },
    ],
  },
];

/* ── Sub-components ─────────────────────────────────────────────────────────── */

function StarIcon() {
  return (
    <svg
      width="12" height="12" viewBox="0 0 24 24"
      fill="currentColor" aria-hidden="true"
      style={{ color: "#f59e0b", flexShrink: 0 }}
    >
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77 5.82 21.02 7 14.14 2 9.27l6.91-1.01L12 2z"/>
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg
      width="11" height="11" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    >
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
      <polyline points="15 3 21 3 21 9"/>
      <line x1="10" y1="14" x2="21" y2="3"/>
    </svg>
  );
}

function ToolCard({ tool }: { tool: AiTool }) {
  return (
    <a
      href={tool.url}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display:         "flex",
        flexDirection:   "column",
        alignItems:      "center",
        gap:             8,
        padding:         "16px 12px",
        borderRadius:    12,
        background:      "var(--bg-card)",
        border:          "1px solid var(--border)",
        textDecoration:  "none",
        transition:      "border-color .15s, transform .15s",
        cursor:          "pointer",
        position:        "relative",
        minWidth:        0,
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--accent-border)";
        (e.currentTarget as HTMLElement).style.transform   = "translateY(-2px)";
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
        (e.currentTarget as HTMLElement).style.transform   = "translateY(0)";
      }}
    >
      {tool.starred && (
        <span style={{ position: "absolute", top: 8, left: 8 }}>
          <StarIcon />
        </span>
      )}
      <span style={{ fontSize: 28, lineHeight: 1 }} aria-hidden="true">
        {tool.emoji}
      </span>
      <span style={{
        fontSize:   12,
        fontWeight: 600,
        color:      "var(--t1)",
        textAlign:  "center",
        lineHeight: 1.3,
      }}>
        {tool.name}
      </span>
      <span style={{
        fontSize:   10,
        color:      "var(--t4)",
        textAlign:  "center",
        lineHeight: 1.4,
      }}>
        {tool.role}
      </span>
      <span style={{
        display:    "flex",
        alignItems: "center",
        gap:        4,
        fontSize:   10,
        color:      "var(--accent-2)",
        marginTop:  2,
      }}>
        Open <ExternalLinkIcon />
      </span>
    </a>
  );
}

/* ── Main component ─────────────────────────────────────────────────────────── */

interface Props {
  section: AppSection;
}

export function AIToolsSectionPanel({ section }: Props) {
  const { t } = useTranslation("designStudio");

  const meta = CATALOGUE.find(c => c.section === section);
  if (!meta) return null;

  const title   = t(`aiToolsPanel.categories.${meta.key}`,        { defaultValue: meta.key });
  const desc    = t(`aiToolsPanel.${meta.descKey}`,               { defaultValue: "" });
  const example = t(`aiToolsPanel.${meta.exampleKey}`,            { defaultValue: "" });

  return (
    <div style={{
      display:       "flex",
      flexDirection: "column",
      height:        "100%",
      overflowY:     "auto",
      padding:       "28px 28px 40px",
      gap:           24,
    }}>
      {/* Header */}
      <div>
        <h2 style={{
          margin:     0,
          fontSize:   20,
          fontWeight: 700,
          color:      "var(--t1)",
          marginBottom: 8,
        }}>
          {title}
        </h2>
        {desc && (
          <p style={{
            margin:     0,
            fontSize:   13,
            color:      "var(--t3)",
            lineHeight: 1.6,
            maxWidth:   520,
          }}>
            {desc}
          </p>
        )}
      </div>

      {/* Tool grid */}
      <div style={{
        display:               "grid",
        gridTemplateColumns:   "repeat(3, 1fr)",
        gap:                   12,
        maxWidth:              480,
      }}>
        {meta.tools.map(tool => (
          <ToolCard key={tool.name} tool={tool} />
        ))}
      </div>

      {/* Example */}
      {example && (
        <div style={{
          padding:      "16px 20px",
          borderRadius: 12,
          background:   "var(--accent-dim)",
          border:       "1px solid var(--accent-border)",
          maxWidth:     520,
        }}>
          <div style={{
            fontSize:     11,
            fontWeight:   700,
            color:        "var(--accent-2)",
            marginBottom: 8,
            textTransform:"uppercase",
            letterSpacing:"0.06em",
          }}>
            {t("aiToolsPanel.exampleLabel", { defaultValue: "Example" })}
          </div>
          <p style={{
            margin:     0,
            fontSize:   13,
            color:      "var(--t2)",
            lineHeight: 1.65,
          }}>
            {example}
          </p>
        </div>
      )}

      {/* Recommended badge */}
      <div style={{
        display:    "flex",
        alignItems: "center",
        gap:        6,
        fontSize:   11,
        color:      "var(--t4)",
      }}>
        <StarIcon />
        <span>{t("aiToolsPanel.starredNote", { defaultValue: "Starred tools are the top recommended pick for this category." })}</span>
      </div>
    </div>
  );
}

