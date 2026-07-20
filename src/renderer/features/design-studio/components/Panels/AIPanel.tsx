/**
 * AIPanel — AI-powered design tools.
 * Text-to-image, color palette, font pairing, design suggestions.
 * Delegates to AIDesignEngine service.
 */
import { useState, useCallback } from "react";
import type { Canvas as FabricCanvas } from "fabric";
import { aiDesignEngine } from "../../features/ai/AIDesignEngine";
import type { DesignSuggestion, FontPairingResult, ColorPaletteResult } from "../../features/ai/AIDesignEngine";

interface Props {
  getCanvas: () => FabricCanvas | null;
}

type Tool = "image" | "palette" | "fonts" | "suggestions";

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

export function AIPanel({ getCanvas }: Props) {
  const [tool, setTool]     = useState<Tool>("image");
  const [busy, setBusy]     = useState(false);
  const [error, setError]   = useState("");

  // Text-to-Image
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
      if (tool === "image") {
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
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }, [tool, imgPrompt, palPrompt, fontStyle, getCanvas]);

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

  const TABS: { id: Tool; label: string }[] = [
    { id: "image",       label: "Image"   },
    { id: "palette",     label: "Palette" },
    { id: "fonts",       label: "Fonts"   },
    { id: "suggestions", label: "Ideas"   },
  ];

  return (
    <div style={s.root}>
      <div style={s.tabs} role="tablist" aria-label="AI tools">
        {TABS.map(t => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tool === t.id}
            style={{
              ...s.tab,
              color: tool === t.id ? "var(--accent-2)" : "#6b7280",
              borderBottomColor: tool === t.id ? "var(--accent-2)" : "transparent",
            }}
            onClick={() => { setTool(t.id); setError(""); }}
          >{t.label}</button>
        ))}
      </div>

      <div style={s.body}>
        {tool === "image" && (
          <>
            <Section label="Describe your image">
              <textarea
                style={{ ...s.input, minHeight: "64px" }}
                value={imgPrompt}
                onChange={e => setImgPrompt(e.target.value)}
                placeholder="A minimalist logo on white background…"
                aria-label="Image prompt"
              />
            </Section>
            <button style={s.btn} onClick={run} disabled={busy || !imgPrompt.trim()}>
              {busy ? "Generating…" : "Generate Image"}
            </button>
            {error && <div style={s.error}>{error}</div>}
            {images.length > 0 && (
              <div style={s.imgGrid}>
                {images.map((src, i) => (
                  <button
                    key={i}
                    type="button"
                    style={{ ...s.genImg, padding: 0, border: "none", background: "none", cursor: "pointer" }}
                    onClick={() => void insertImage(src)}
                    title="Click to add to canvas"
                    aria-label={`Add generated image ${i + 1} to canvas`}
                  >
                    <img src={src} alt={`Generated ${i + 1}`} style={{ width: "100%", height: "100%", display: "block" }} />
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {tool === "palette" && (
          <>
            <Section label="Describe your brand or mood">
              <input
                style={s.input}
                value={palPrompt}
                onChange={e => setPalPrompt(e.target.value)}
                placeholder="Ocean, calm, professional…"
                aria-label="Palette prompt"
              />
            </Section>
            <button style={s.btn} onClick={run} disabled={busy || !palPrompt.trim()}>
              {busy ? "Generating…" : "Generate Palette"}
            </button>
            {error && <div style={s.error}>{error}</div>}
            {palette.length > 0 && (
              <div style={s.colorRow}>
                {palette.map((c, i) => (
                  <div key={i} style={{ ...s.swatch, background: c.hex }} title={`${c.name}: ${c.hex}`} />
                ))}
              </div>
            )}
          </>
        )}

        {tool === "fonts" && (
          <>
            <Section label="Style">
              <select
                style={s.input}
                value={fontStyle}
                onChange={e => setFontStyle(e.target.value)}
                aria-label="Font style"
              >
                {["modern", "classic", "playful", "minimal", "bold"].map(v => (
                  <option key={v} value={v}>{v.charAt(0).toUpperCase() + v.slice(1)}</option>
                ))}
              </select>
            </Section>
            <button style={s.btn} onClick={run} disabled={busy}>
              {busy ? "Pairing…" : "Get Font Pairings"}
            </button>
            {error && <div style={s.error}>{error}</div>}
            {fontPairs.map((pair, i) => (
              <div key={i} style={s.fontItem}>
                <div style={{ ...s.fontH, fontFamily: pair.heading.family }}>{pair.heading.family}</div>
                <div style={{ ...s.fontSub, fontFamily: pair.body.family }}>Body: {pair.body.family} · {pair.label}</div>
              </div>
            ))}
          </>
        )}

        {tool === "suggestions" && (
          <>
            <p style={{ fontSize: "12px", color: "#9ca3af", marginTop: 0 }}>
              Analyzes your current canvas and suggests improvements.
            </p>
            <button style={s.btn} onClick={run} disabled={busy}>
              {busy ? "Analyzing…" : "Analyze Canvas"}
            </button>
            {error && <div style={s.error}>{error}</div>}
            {busy && <div style={s.loading}>Thinking…</div>}
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
