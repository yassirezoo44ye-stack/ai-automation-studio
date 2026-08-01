/**
 * AIPanel — AI-powered design tools.
 * Full-design generation, color palette, font pairing, design suggestions.
 * Delegates to AIDesignEngine service.
 */
import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { Canvas as FabricCanvas } from "fabric";
import { aiDesignEngine } from "../../features/ai/AIDesignEngine";
import type { DesignSuggestion, FontPairingResult, ColorPaletteResult } from "../../features/ai/AIDesignEngine";

interface Props {
  getCanvas:     () => FabricCanvas | null;
  onApplyDesign: (canvasJson: object, width: number, height: number) => void;
}

type Tool = "generate" | "image" | "palette" | "fonts" | "suggestions";

// Mirrors DESIGN_SIZES in app/routers/design.py — keys are sent to the
// backend verbatim, so they stay in English regardless of UI language.
const DESIGN_TEMPLATES: { key: string; labelKey: string; width: number; height: number }[] = [
  { key: "Instagram Post",  labelKey: "instagramPost",  width: 1080, height: 1080 },
  { key: "Instagram Story", labelKey: "instagramStory", width: 1080, height: 1920 },
  { key: "Facebook Cover",  labelKey: "facebookCover",  width: 820,  height: 312  },
  { key: "Facebook Post",   labelKey: "facebookPost",   width: 1200, height: 630  },
  { key: "YouTube Thumb",   labelKey: "youtubeThumb",   width: 1280, height: 720  },
  { key: "A4 Portrait",     labelKey: "a4Portrait",     width: 794,  height: 1123 },
  { key: "Presentation",    labelKey: "presentation",   width: 1920, height: 1080 },
];

const s: Record<string, React.CSSProperties> = {
  root:     { display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" },
  tabs:     { display: "flex", borderBottom: "1px solid #1f2937" },
  tab:      { flex: 1, padding: "8px 4px", fontSize: "11px", border: "none", background: "transparent", cursor: "pointer", borderBottom: "2px solid transparent" },
  body:     { flex: 1, overflowY: "auto", padding: "12px 10px" },
  label:    { fontSize: "11px", color: "#9ca3af", marginBottom: "4px" },
  input:    { width: "100%", padding: "6px 8px", fontSize: "12px", border: "1px solid #374151", borderRadius: "4px", background: "#1f2937", color: "#f9fafb", outline: "none", boxSizing: "border-box" as const, resize: "vertical" as const },
  btn:      { width: "100%", padding: "7px 12px", fontSize: "12px", background: "#4f46e5", color: "#fff", border: "none", borderRadius: "5px", cursor: "pointer", marginTop: "8px" },
  result:   { marginTop: "10px" },
  imgGrid:  { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginTop: "8px" },
  genImg:   { width: "100%", aspectRatio: "1", objectFit: "cover" as const, borderRadius: "4px", border: "1px solid #374151", cursor: "pointer" },
  comingSoon: { color: "#6b7280", fontSize: "11px", marginTop: "6px", textAlign: "center" as const },
  colorRow: { display: "flex", gap: "6px", flexWrap: "wrap" as const, marginTop: "8px" },
  swatch:   { width: "36px", height: "36px", borderRadius: "6px", border: "1px solid #374151", cursor: "pointer", position: "relative" as const },
  fontItem: { padding: "8px", borderRadius: "6px", border: "1px solid #374151", marginTop: "6px", background: "#1f2937" },
  fontH:    { fontSize: "14px", fontWeight: 700, color: "#f9fafb" },
  fontSub:  { fontSize: "11px", color: "#9ca3af", marginTop: "2px" },
  suggItem: { padding: "8px 10px", borderRadius: "6px", border: "1px solid #374151", marginTop: "6px", background: "#1f2937", cursor: "pointer" },
  suggTitle:{ fontSize: "12px", fontWeight: 600, color: "#c7d2fe" },
  suggDesc: { fontSize: "11px", color: "#9ca3af", marginTop: "2px" },
  error:    { color: "#f87171", fontSize: "11px", marginTop: "6px" },
  loading:  { color: "#6b7280", fontSize: "12px", textAlign: "center" as const, padding: "16px 0" },
};

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return <div style={{ marginBottom: "10px" }}><div style={s.label}>{label}</div>{children}</div>;
}

export function AIPanel({ getCanvas, onApplyDesign }: Props) {
  const { t } = useTranslation("designStudio");
  const [tool, setTool]     = useState<Tool>("generate");
  const [busy, setBusy]     = useState(false);
  const [error, setError]   = useState("");

  // Generate full design
  const [genPrompt, setGenPrompt] = useState("");
  const [genTemplate, setGenTemplate] = useState(DESIGN_TEMPLATES[0].key);

  // Text-to-Image — no backend yet; kept dormant with its Generate button
  // disabled (see aiPanel.comingSoon) rather than deleted.
  const [imgPrompt, setImgPrompt] = useState("");
  const [images, setImages]       = useState<string[]>([]);

  // Color Palette
  const [palPrompt, setPalPrompt] = useState("");
  const [palette, setPalette]     = useState<ColorPaletteResult["colors"]>([]);

  // Font Pairings
  const [fontStyle, setFontStyle] = useState("modern");
  const [fontPairs, setFontPairs] = useState<FontPairingResult["pairs"]>([]);

  // Suggestions
  const [suggestions, setSuggestions] = useState<DesignSuggestion[]>([]);

  const run = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      if (tool === "generate") {
        const tpl = DESIGN_TEMPLATES.find(t => t.key === genTemplate) ?? DESIGN_TEMPLATES[0];
        const res = await aiDesignEngine.generateDesign({ prompt: genPrompt, template: tpl.key });
        onApplyDesign(res.canvas_json, tpl.width, tpl.height);
      } else if (tool === "image") {
        const res = await aiDesignEngine.textToImage({ prompt: imgPrompt, width: 512, height: 512 });
        setImages(res.images);
      } else if (tool === "palette") {
        const res = await aiDesignEngine.generateColorPalette({ prompt: palPrompt, count: 5, mode: "complementary" });
        setPalette(res.colors);
      } else if (tool === "fonts") {
        const res = await aiDesignEngine.getFontPairings({ style: fontStyle, usage: "ui" });
        setFontPairs(res.pairs);
      } else if (tool === "suggestions") {
        const fc = getCanvas();
        const json = fc ? fc.toObject(["_meta"]) : {};
        const res = await aiDesignEngine.getSuggestions(json);
        setSuggestions(res);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t("aiPanel.requestFailed"));
    } finally {
      setBusy(false);
    }
  }, [tool, genPrompt, genTemplate, onApplyDesign, imgPrompt, palPrompt, fontStyle, getCanvas, t]);

  const insertImage = async (src: string) => {
    const fc = getCanvas();
    if (!fc) return;
    try {
      const { FabricImage } = await import("fabric");
      const img = await FabricImage.fromURL(src);
      img.scale(0.5);
      fc.add(img);
      fc.setActiveObject(img);
      fc.renderAll();
    } catch { /* noop */ }
  };

  const TAB_IDS: Tool[] = ["generate", "image", "palette", "fonts", "suggestions"];

  return (
    <div style={s.root}>
      <div style={s.tabs} role="tablist" aria-label={t("aiPanel.toolsAriaLabel")}>
        {TAB_IDS.map(id => (
          <button
            key={id}
            role="tab"
            aria-selected={tool === id}
            style={{
              ...s.tab,
              color: tool === id ? "var(--accent-2)" : "#6b7280",
              borderBottomColor: tool === id ? "var(--accent-2)" : "transparent",
            }}
            onClick={() => { setTool(id); setError(""); }}
          >{t(`aiPanel.tabs.${id}`)}</button>
        ))}
      </div>

      <div style={s.body}>
        {tool === "generate" && (
          <>
            <Section label={t("aiPanel.describeDesign")}>
              <textarea
                style={{ ...s.input, minHeight: "64px" }}
                value={genPrompt}
                onChange={e => setGenPrompt(e.target.value)}
                placeholder={t("aiPanel.designPromptPlaceholder")}
                aria-label={t("aiPanel.designPromptAriaLabel")}
              />
            </Section>
            <Section label={t("aiPanel.designFormat")}>
              <select
                style={s.input}
                value={genTemplate}
                onChange={e => setGenTemplate(e.target.value)}
                aria-label={t("aiPanel.designFormatAriaLabel")}
              >
                {DESIGN_TEMPLATES.map(tpl => (
                  <option key={tpl.key} value={tpl.key}>{t(`aiPanel.designFormats.${tpl.labelKey}`)}</option>
                ))}
              </select>
            </Section>
            <button style={s.btn} onClick={run} disabled={busy || !genPrompt.trim()}>
              {busy ? t("aiPanel.generating") : t("aiPanel.generateDesign")}
            </button>
            {error && <div style={s.error}>{error}</div>}
          </>
        )}

        {tool === "image" && (
          <>
            <Section label={t("aiPanel.describeImage")}>
              <textarea
                style={{ ...s.input, minHeight: "64px" }}
                value={imgPrompt}
                onChange={e => setImgPrompt(e.target.value)}
                placeholder={t("aiPanel.imagePromptPlaceholder")}
                aria-label={t("aiPanel.imagePromptAriaLabel")}
              />
            </Section>
            <button style={s.btn} disabled title={t("aiPanel.comingSoon")}>
              {t("aiPanel.generateImage")}
            </button>
            <div style={s.comingSoon}>{t("aiPanel.comingSoon")}</div>
            {images.length > 0 && (
              <div style={s.imgGrid}>
                {images.map((src, i) => (
                  <button
                    key={i}
                    type="button"
                    style={{ ...s.genImg, padding: 0, border: "none", background: "none", cursor: "pointer" }}
                    onClick={() => void insertImage(src)}
                    title={t("aiPanel.addToCanvasTitle")}
                    aria-label={t("aiPanel.addGeneratedImageAriaLabel", { num: i + 1 })}
                  >
                    <img src={src} alt={t("aiPanel.generatedImageAlt", { num: i + 1 })} style={{ width: "100%", height: "100%", display: "block" }} />
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {tool === "palette" && (
          <>
            <Section label={t("aiPanel.describeBrand")}>
              <input
                style={s.input}
                value={palPrompt}
                onChange={e => setPalPrompt(e.target.value)}
                placeholder={t("aiPanel.palettePromptPlaceholder")}
                aria-label={t("aiPanel.palettePromptAriaLabel")}
              />
            </Section>
            <button style={s.btn} onClick={run} disabled={busy || !palPrompt.trim()}>
              {busy ? t("aiPanel.generating") : t("aiPanel.generatePalette")}
            </button>
            {error && <div style={s.error}>{error}</div>}
            {palette.length > 0 && (
              <div style={s.colorRow}>
                {palette.map((c, i) => (
                  <div key={i} style={{ ...s.swatch, background: c.hex }} title={t("aiPanel.colorSwatchTitle", { name: c.name, hex: c.hex })} />
                ))}
              </div>
            )}
          </>
        )}

        {tool === "fonts" && (
          <>
            <Section label={t("aiPanel.style")}>
              <select
                style={s.input}
                value={fontStyle}
                onChange={e => setFontStyle(e.target.value)}
                aria-label={t("aiPanel.fontStyleAriaLabel")}
              >
                {(["modern", "classic", "playful", "minimal", "bold"] as const).map(v => (
                  <option key={v} value={v}>{t(`aiPanel.fontStyles.${v}`)}</option>
                ))}
              </select>
            </Section>
            <button style={s.btn} onClick={run} disabled={busy}>
              {busy ? t("aiPanel.pairing") : t("aiPanel.getFontPairings")}
            </button>
            {error && <div style={s.error}>{error}</div>}
            {fontPairs.map((pair, i) => (
              <div key={i} style={s.fontItem}>
                <div style={{ ...s.fontH, fontFamily: pair.heading.family }}>{pair.heading.family}</div>
                <div style={{ ...s.fontSub, fontFamily: pair.body.family }}>{t("aiPanel.bodyLabel", { family: pair.body.family, label: pair.label })}</div>
              </div>
            ))}
          </>
        )}

        {tool === "suggestions" && (
          <>
            <p style={{ fontSize: "12px", color: "#9ca3af", marginTop: 0 }}>
              {t("aiPanel.suggestionsDescription")}
            </p>
            <button style={s.btn} onClick={run} disabled={busy}>
              {busy ? t("aiPanel.analyzing") : t("aiPanel.analyzeCanvas")}
            </button>
            {error && <div style={s.error}>{error}</div>}
            {busy && <div style={s.loading}>{t("aiPanel.thinking")}</div>}
            {suggestions.map((sug, i) => (
              <div key={i} style={s.suggItem}>
                <div style={s.suggTitle}>{sug.title}</div>
                <div style={s.suggDesc}>{sug.summary}</div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
