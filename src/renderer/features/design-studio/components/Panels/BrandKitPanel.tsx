/**
 * BrandKitPanel — visual panel for managing brand colors, fonts, and logos.
 * Reads state.brandKit (kept in sync by useBrandKit() via BrandKitChanged)
 * and writes through brandKitActions, which persist via BrandKitService.
 *
 * All colours use CSS tokens — fully light/dark/high-contrast aware.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useDesign } from "../../stores/designStore";
import type { BrandKit, BrandColor, BrandFont, BrandLogo } from "../../types/canvas.types";
import { brandKitActions } from "../../features/brand-kit/actions/brandKitActions";

// ── Token-based style constants ───────────────────────────────────────────────

const root: React.CSSProperties = {
  display: "flex", flexDirection: "column",
  height: "100%", overflowY: "auto", padding: "10px",
};
const section: React.CSSProperties = { marginBottom: "18px" };
const secTitle: React.CSSProperties = {
  fontSize: "10px", fontWeight: 700, color: "var(--t3)",
  textTransform: "uppercase", letterSpacing: "0.08em",
  marginBottom: "8px", display: "flex", alignItems: "center", justifyContent: "space-between",
};
const addBtn: React.CSSProperties = {
  fontSize: "16px", lineHeight: 1,
  background: "none", border: "none",
  color: "var(--fill-accent)", cursor: "pointer", padding: "0 4px",
};
const colorGrid: React.CSSProperties = { display: "flex", flexWrap: "wrap", gap: "6px" };
const swatchDel: React.CSSProperties = {
  position: "absolute", top: "-4px", insetInlineEnd: "-4px",
  width: "14px", height: "14px", borderRadius: "50%",
  background: "var(--red)", color: "#fff",
  fontSize: "9px", display: "flex", alignItems: "center", justifyContent: "center",
  cursor: "pointer", border: "none", lineHeight: 1,
};
const fontItem: React.CSSProperties = {
  padding: "6px 8px", borderRadius: "var(--r-xs, 6px)",
  background: "var(--bg-input)", border: "1px solid var(--border)",
  marginBottom: "4px", display: "flex", alignItems: "center", justifyContent: "space-between",
};
const fontSub: React.CSSProperties = { fontSize: "10px", color: "var(--t4)" };
const logoItem: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: "8px", padding: "4px 0",
  borderBottom: "1px solid var(--b1)",
};
const logoThumb: React.CSSProperties = {
  width: "40px", height: "28px",
  background: "var(--bg-input)", borderRadius: "var(--r-xs, 4px)",
  border: "1px solid var(--border)", objectFit: "contain",
};
const delBtn: React.CSSProperties = {
  background: "none", border: "none", color: "var(--t3)",
  cursor: "pointer", fontSize: "14px", lineHeight: 1,
};
const emptyNote: React.CSSProperties = {
  color: "var(--t4)", fontSize: "12px", textAlign: "center",
  padding: "8px 0", fontStyle: "italic",
};
const addColorBtn: React.CSSProperties = {
  padding: 0, width: "32px", height: "32px",
  borderRadius: "var(--r-xs, 6px)", border: "2px dashed var(--border)",
  cursor: "pointer", background: "transparent", color: "var(--t3)",
  fontSize: "18px", display: "flex", alignItems: "center", justifyContent: "center",
};

// ── Component ─────────────────────────────────────────────────────────────────

export function BrandKitPanel() {
  const { t } = useTranslation("designStudio");
  const { state } = useDesign();
  const kit = state.brandKit as BrandKit;

  // Colors
  const [newColor,    setNewColor]    = useState("#4f46e5");
  const [addingColor, setAddingColor] = useState(false);

  const addColor = () => {
    setAddingColor(false);
    brandKitActions.addColor({ name: newColor, value: newColor })
      .catch(err => console.error("[brand-kit] addColor failed", err));
  };
  const removeColor = (id: string) => {
    brandKitActions.removeColor(id)
      .catch(err => console.error("[brand-kit] removeColor failed", err));
  };

  // Fonts
  const addFont = () => {
    const family = window.prompt(t("brandKitPanel.fontFamilyPrompt"));
    if (!family) return;
    brandKitActions.addFont({ family })
      .catch(err => console.error("[brand-kit] addFont failed", err));
  };
  const removeFont = (id: string) => {
    brandKitActions.removeFont(id)
      .catch(err => console.error("[brand-kit] removeFont failed", err));
  };

  // Logos
  const addLogo = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        brandKitActions
          .addLogo({ name: file.name, src: reader.result as string })
          .catch(err => console.error("[brand-kit] addLogo failed", err));
      };
      reader.readAsDataURL(file);
    };
    input.click();
  };
  const removeLogo = (id: string) => {
    brandKitActions.removeLogo(id)
      .catch(err => console.error("[brand-kit] removeLogo failed", err));
  };

  return (
    <div style={root}>
      {/* ── Colors ─────────────────────────────────────────────────── */}
      <div style={section}>
        <div style={secTitle}>
          <span>{t("brandKitPanel.brandColors")}</span>
          <button style={addBtn} onClick={() => setAddingColor(v => !v)} aria-label={t("brandKitPanel.addColorAriaLabel")}>+</button>
        </div>
        <div style={colorGrid}>
          {kit.colors.map((c: BrandColor) => (
            <div
              key={c.id}
              style={{
                width: "32px", height: "32px", borderRadius: "var(--r-xs, 6px)",
                border: "1px solid var(--border)", cursor: "pointer",
                position: "relative", flexShrink: 0, background: c.value,
              }}
              title={c.name}
            >
              <button
                style={swatchDel}
                onClick={() => removeColor(c.id)}
                aria-label={t("brandKitPanel.removeColorAriaLabel", { name: c.name })}
              >✕</button>
            </div>
          ))}

          {addingColor ? (
            <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
              <input
                type="color"
                value={newColor}
                onChange={e => setNewColor(e.target.value)}
                style={{ width: "32px", height: "32px", padding: 0, border: "none", cursor: "pointer", borderRadius: "var(--r-xs, 6px)" }}
                aria-label={t("brandKitPanel.pickColorAriaLabel")}
              />
              <button
                style={{
                  padding: "4px 8px", fontSize: "12px",
                  background: "var(--fill-accent)", color: "#fff",
                  border: "none", borderRadius: "var(--r-xs, 4px)", cursor: "pointer",
                }}
                onClick={addColor}
              >{t("brandKitPanel.add")}</button>
            </div>
          ) : (
            <button style={addColorBtn} onClick={() => setAddingColor(true)} aria-label={t("brandKitPanel.addBrandColorAriaLabel")}>+</button>
          )}
        </div>
        {!kit.colors.length && !addingColor && (
          <div style={emptyNote}>{t("brandKitPanel.noBrandColors")}</div>
        )}
      </div>

      {/* ── Fonts ──────────────────────────────────────────────────── */}
      <div style={section}>
        <div style={secTitle}>
          <span>{t("brandKitPanel.brandFonts")}</span>
          <button style={addBtn} onClick={addFont} aria-label={t("brandKitPanel.addFontAriaLabel")}>+</button>
        </div>
        {kit.fonts.length === 0 && <div style={emptyNote}>{t("brandKitPanel.noBrandFonts")}</div>}
        {kit.fonts.map((f: BrandFont) => (
          <div key={f.id} style={fontItem}>
            <div>
              <div style={{ fontSize: "13px", color: "var(--t1)", fontFamily: f.family }}>{f.name}</div>
              <div style={fontSub}>{f.weights.join(", ")}</div>
            </div>
            <button style={delBtn} onClick={() => removeFont(f.id)} aria-label={t("brandKitPanel.removeFontAriaLabel", { name: f.name })}>✕</button>
          </div>
        ))}
      </div>

      {/* ── Logos ──────────────────────────────────────────────────── */}
      <div style={section}>
        <div style={secTitle}>
          <span>{t("brandKitPanel.logos")}</span>
          <button style={addBtn} onClick={addLogo} aria-label={t("brandKitPanel.uploadLogoAriaLabel")}>+</button>
        </div>
        {kit.logos.length === 0 && <div style={emptyNote}>{t("brandKitPanel.noLogosYet")}</div>}
        {kit.logos.map((l: BrandLogo) => (
          <div key={l.id} style={logoItem}>
            <img src={l.src} style={logoThumb} alt={l.name} />
            <span style={{
              flex: 1, fontSize: "12px", color: "var(--t2)",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>{l.name}</span>
            <button style={delBtn} onClick={() => removeLogo(l.id)} aria-label={t("brandKitPanel.removeLogoAriaLabel", { name: l.name })}>✕</button>
          </div>
        ))}
      </div>
    </div>
  );
}
