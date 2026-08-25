/**
 * AIPanel — AI-powered design tools.
 * Full-design generation, color palette, font pairing, design suggestions.
 * Delegates to AIDesignEngine service.
 *
 * All colours use CSS tokens — fully light/dark/high-contrast aware.
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

// Mirrors DESIGN_SIZES in app/routers/design.py
const DESIGN_TEMPLATES: { key: string; labelKey: string; width: number; height: number }[] = [
  { key: "Instagram Post",  labelKey: "instagramPost",  width: 1080, height: 1080 },
  { key: "Instagram Story", labelKey: "instagramStory", width: 1080, height: 1920 },
  { key: "Facebook Cover",  labelKey: "facebookCover",  width: 820,  height: 312  },
  { key: "Facebook Post",   labelKey: "facebookPost",   width: 1200, height: 630  },
  { key: "YouTube Thumb",   labelKey: "youtubeThumb",   width: 1280, height: 720  },
  { key: "A4 Portrait",     labelKey: "a4Portrait",     width: 794,  height: 1123 },
  { key: "Presentation",    labelKey: "presentation",   width: 1920, height: 1080 },
];

// ── Token-based style constants ───────────────────────────────────────────────

const panelRoot: React.CSSProperties = { display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" };
const tabBar: React.CSSProperties = { display: "flex", borderBottom: "1px solid var(--b1)", flexShrink: 0 };
const tabBase: React.CSSProperties = {
  flex: 1, padding: "8px 4px", fontSize: "10px", border: "none",
  background: "transparent", cursor: "pointer", borderBottom: "2px solid transparent",
  fontFamily: "inherit", transition: "color 0.15s, border-color 0.15s",
};
const body: React.CSSProperties = { flex: 1, overflowY: "auto", padding: "12px 10px" };
const inputBase: React.CSSProperties = {
  width: "100%", padding: "6px 8px", fontSize: "12px",
  border: "1px solid var(--border)", borderRadius: "var(--r-xs, 4px)",
  background: "var(--bg-input)", color: "var(--t1)",
  outline: "none", boxSizing: "border-box", resize: "vertical",
  fontFamily: "inherit",
};
const btnStyle: React.CSSProperties = {
  width: "100%", padding: "7px 12px", fontSize: "12px",
  background: "var(--fill-accent)", color: "#fff",
  border: "none", borderRadius: "var(--r-xs, 5px)",
  cursor: "pointer", marginTop: "8px", fontFamily: "inherit",
  transition: "opacity 0.15s",
};
const btnDisabled: React.CSSProperties = { ...btnStyle, opacity: 0.5, cursor: "not-allowed" };
const colorRow: React.CSSProperties = { display: "flex", gap: "6px", flexWrap: "wrap", marginTop: "8px" };
const swatch: React.CSSProperties = {
  width: "36px", height: "36px", borderRadius: "var(--r-xs, 6px)",
  border: "1px solid var(--border)", cursor: "pointer", position: "relative",
};
const fontItemStyle: React.CSSProperties = {
  padding: "8px", borderRadius: "var(--r-xs, 6px)",
  border: "1px solid var(--border)", marginTop: "6px",
  background: "var(--bg-input)",
};
const suggItem: React.CSSProperties = {
  padding: "8px 10px", borderRadius: "var(--r-xs, 6px)",
  border: "1px solid var(--border)", marginTop: "6px",
  background: "var(--bg-input)", cursor: "pointer",
};
const imgGrid: React.CSSProperties = {
  display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginTop: "8px",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "10px" }}>
      <div style={{ fontSize: "11px", color: "var(--t3)", marginBottom: "4px" }}>{label}</div>
      {children}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AIPanel({ getCanvas, onApplyDesign }: Props) {
  const { t } = useTranslation("designStudio");
  const [tool, setTool]   = useState<Tool>("generate");
  const [busy, setBusy]   = useState(false);
  const [error, setError] = useState("");

  // Generate full design
  const [genPrompt,   setGenPrompt]   = useState("");
  const [genTemplate, setGenTemplate] = useState(DESIGN_TEMPLATES[0].key);

  // Text-to-Image — kept dormant, button disabled
  const [imgPrompt, setImgPrompt] = useState("");
  const [images,    setImages]    = useState<string[]>([]);

  // Color Palette
  const [palPrompt, setPalPrompt] = useState("");
  const [palette,   setPalette]   = useState<ColorPaletteResult["colors"]>([]);

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
    <div style={panelRoot}>
      {/* ── Tab bar ────────────────────────────────────────────────── */}
      <div style={tabBar} role="tablist" aria-label={t("aiPanel.toolsAriaLabel")}>
        {TAB_IDS.map(id => (
          <button
            key={id}
            role="tab"
            aria-selected={tool === id}
            style={{
              ...tabBase,
              color: tool === id ? "var(--fill-accent)" : "var(--t3)",
              borderBottomColor: tool === id ? "var(--fill-accent)" : "transparent",
              fontWeight: tool === id ? 600 : 400,
            }}
            onClick={() => { setTool(id); setError(""); }}
          >
            {t(`aiPanel.tabs.${id}`)}
          </button>
        ))}
      </div>

      {/* ── Body ───────────────────────────────────────────────────── */}
      <div style={body}>

        {/* Generate Design */}
        {tool === "generate" && (
          <>
            <SectionLabel label={t("aiPanel.describeDesign")}>
              <textarea
                style={{ ...inputBase, minHeight: "64px" }}
                value={genPrompt}
                onChange={e => setGenPrompt(e.target.value)}
                placeholder={t("aiPanel.designPromptPlaceholder")}
                aria-label={t("aiPanel.designPromptAriaLabel")}
              />
            </SectionLabel>
            <SectionLabel label={t("aiPanel.designFormat")}>
              <select
                style={{ ...inputBase, resize: "none" }}
                value={genTemplate}
                onChange={e => setGenTemplate(e.target.value)}
                aria-label={t("aiPanel.designFormatAriaLabel")}
              >
                {DESIGN_TEMPLATES.map(tpl => (
                  <option key={tpl.key} value={tpl.key}>{t(`aiPanel.designFormats.${tpl.labelKey}`)}</option>
                ))}
              </select>
            </SectionLabel>
            <button
              style={busy || !genPrompt.trim() ? btnDisabled : btnStyle}
              onClick={run}
              disabled={busy || !genPrompt.trim()}
            >
              {busy ? t("aiPanel.generating") : t("aiPanel.generateDesign")}
            </button>
            {error && <div style={{ color: "var(--text-danger)", fontSize: "11px", marginTop: "6px" }}>{error}</div>}
          </>
        )}

        {/* Text-to-Image (Coming Soon) */}
        {tool === "image" && (
          <>
            <SectionLabel label={t("aiPanel.describeImage")}>
              <textarea
                style={{ ...inputBase, minHeight: "64px" }}
                value={imgPrompt}
                onChange={e => setImgPrompt(e.target.value)}
                placeholder={t("aiPanel.imagePromptPlaceholder")}
                aria-label={t("aiPanel.imagePromptAriaLabel")}
              />
            </SectionLabel>
            <button style={btnDisabled} disabled title={t("aiPanel.comingSoon")}>
              {t("aiPanel.generateImage")}
            </button>
            <div style={{ color: "var(--t4)", fontSize: "11px", marginTop: "6px", textAlign: "center" }}>
              {t("aiPanel.comingSoon")}
            </div>
            {images.length > 0 && (
              <div style={imgGrid}>
                {images.map((src, i) => (
                  <button
                    key={i}
                    type="button"
                    style={{ padding: 0, border: "none", background: "none", cursor: "pointer", borderRadius: "var(--r-xs, 4px)", overflow: "hidden" }}
                    onClick={() => void insertImage(src)}
                    title={t("aiPanel.addToCanvasTitle")}
                    aria-label={t("aiPanel.addGeneratedImageAriaLabel", { num: i + 1 })}
                  >
                    <img
                      src={src}
                      alt={t("aiPanel.generatedImageAlt", { num: i + 1 })}
                      style={{ width: "100%", aspectRatio: "1", objectFit: "cover", display: "block" }}
                    />
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {/* Color Palette */}
        {tool === "palette" && (
          <>
            <SectionLabel label={t("aiPanel.describeBrand")}>
              <input
                style={{ ...inputBase, resize: "none" }}
                value={palPrompt}
                onChange={e => setPalPrompt(e.target.value)}
                placeholder={t("aiPanel.palettePromptPlaceholder")}
                aria-label={t("aiPanel.palettePromptAriaLabel")}
              />
            </SectionLabel>
            <button
              style={busy || !palPrompt.trim() ? btnDisabled : btnStyle}
              onClick={run}
              disabled={busy || !palPrompt.trim()}
            >
              {busy ? t("aiPanel.generating") : t("aiPanel.generatePalette")}
            </button>
            {error && <div style={{ color: "var(--text-danger)", fontSize: "11px", marginTop: "6px" }}>{error}</div>}
            {palette.length > 0 && (
              <div style={colorRow}>
                {palette.map((c, i) => (
                  <div key={i} style={{ ...swatch, background: c.hex }}
                    title={t("aiPanel.colorSwatchTitle", { name: c.name, hex: c.hex })} />
                ))}
              </div>
            )}
          </>
        )}

        {/* Font Pairings */}
        {tool === "fonts" && (
          <>
            <SectionLabel label={t("aiPanel.style")}>
              <select
                style={{ ...inputBase, resize: "none" }}
                value={fontStyle}
                onChange={e => setFontStyle(e.target.value)}
                aria-label={t("aiPanel.fontStyleAriaLabel")}
              >
                {(["modern", "classic", "playful", "minimal", "bold"] as const).map(v => (
                  <option key={v} value={v}>{t(`aiPanel.fontStyles.${v}`)}</option>
                ))}
              </select>
            </SectionLabel>
            <button style={busy ? btnDisabled : btnStyle} onClick={run} disabled={busy}>
              {busy ? t("aiPanel.pairing") : t("aiPanel.getFontPairings")}
            </button>
            {error && <div style={{ color: "var(--text-danger)", fontSize: "11px", marginTop: "6px" }}>{error}</div>}
            {fontPairs.map((pair, i) => (
              <div key={i} style={fontItemStyle}>
                <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--t1)", fontFamily: pair.heading.family }}>
                  {pair.heading.family}
                </div>
                <div style={{ fontSize: "11px", color: "var(--t3)", marginTop: "2px", fontFamily: pair.body.family }}>
                  {t("aiPanel.bodyLabel", { family: pair.body.family, label: pair.label })}
                </div>
              </div>
            ))}
          </>
        )}

        {/* Suggestions */}
        {tool === "suggestions" && (
          <>
            <p style={{ fontSize: "12px", color: "var(--t3)", marginTop: 0, marginBottom: "10px", lineHeight: 1.5 }}>
              {t("aiPanel.suggestionsDescription")}
            </p>
            <button style={busy ? btnDisabled : btnStyle} onClick={run} disabled={busy}>
              {busy ? t("aiPanel.analyzing") : t("aiPanel.analyzeCanvas")}
            </button>
            {error && <div style={{ color: "var(--text-danger)", fontSize: "11px", marginTop: "6px" }}>{error}</div>}
            {busy && (
              <div style={{ color: "var(--t3)", fontSize: "12px", textAlign: "center", padding: "16px 0" }}>
                {t("aiPanel.thinking")}
              </div>
            )}
            {suggestions.map((sug, i) => (
              <div key={i} style={suggItem}>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-accent)" }}>{sug.title}</div>
                <div style={{ fontSize: "11px", color: "var(--t3)", marginTop: "2px" }}>{sug.summary}</div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
