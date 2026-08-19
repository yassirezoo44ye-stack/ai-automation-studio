/**
 * Golden Design System primitives — the unified Button/Card/Dialog/KPI
 * components every screen shares. Styled via design-system.css classes
 * (g-btn*, g-card, g-dialog*, g-kpi) — not inline styles — and animated
 * with framer-motion, honoring prefers-reduced-motion throughout.
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

/* ── Button ─────────────────────────────────────────────────────────────── */

export function GoldButton({
  children, onClick, variant = "primary", disabled, type = "button", title, style,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
  /** Escape hatch for layout only (e.g. width: "100%") — visual styling stays in the g-btn* classes. */
  style?: CSSProperties;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.button
      type={type}
      title={title}
      className={`g-btn g-btn--${variant}`}
      onClick={onClick}
      disabled={disabled}
      style={style}
      whileTap={reduce || disabled ? undefined : { scale: 0.97 }}
      whileHover={reduce || disabled ? undefined : { y: -1 }}
    >
      {children}
    </motion.button>
  );
}

/* ── Card ───────────────────────────────────────────────────────────────── */

export function GlassCard({
  children, onClick, className = "", lift = true, style,
}: {
  children: ReactNode;
  onClick?: () => void;
  className?: string;
  lift?: boolean;
  style?: CSSProperties;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={`g-card ${className}`}
      onClick={onClick}
      whileHover={reduce || !lift ? undefined : { y: -3 }}
      transition={{ type: "spring", stiffness: 380, damping: 26 }}
      style={onClick ? { cursor: "pointer", ...style } : style}
    >
      {children}
    </motion.div>
  );
}

/* ── Dialog ─────────────────────────────────────────────────────────────── */

/**
 * Stable portal root — created once at module load and never removed by React.
 * Using a dedicated container (rather than document.body directly) prevents
 * the double-removeChild crash that happens when AnimatePresence's exit
 * animation is still running while React unmounts the Dialog's host tree:
 * React removes the portal node from document.body, then framer-motion's
 * cleanup tries to remove the same already-gone node → "not a child" error.
 * A stable container that is never itself removed by React sidesteps this.
 */
const _dialogPortalRoot: Element =
  typeof document !== "undefined"
    ? (() => {
        const existing = document.getElementById("g-dialog-portal-root");
        if (existing) return existing;
        const el = document.createElement("div");
        el.id = "g-dialog-portal-root";
        document.body.appendChild(el);
        return el;
      })()
    : (null as unknown as Element);

export function Dialog({
  open, onClose, title, children, width = 480,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  width?: number;
}) {
  const reduce = useReducedMotion();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    // Move focus into the dialog for keyboard/screen-reader users.
    panelRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="g-dialog-overlay"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: reduce ? 0 : 0.16 }}
          onClick={onClose}
        >
          <motion.div
            ref={panelRef}
            className="g-dialog"
            role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}
            style={{ maxWidth: width }}
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.94, y: 10 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: 6 }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
            onClick={e => e.stopPropagation()}
          >
            <div className="g-dialog__header">
              <span className="g-dialog__title">{title}</span>
              <button className="g-dialog__close" onClick={onClose} aria-label="Close">×</button>
            </div>
            <div className="g-dialog__body">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    _dialogPortalRoot ?? document.body,
  );
}

/* ── KPI card with animated count-up ────────────────────────────────────── */

export function KpiCard({
  label, value, suffix = "", icon, accent = false, displayOverride,
}: {
  label: string;
  value: number;
  suffix?: string;
  icon?: ReactNode;
  accent?: boolean;
  /** Renders this string instead of the animated number — for zero-data
   * states where e.g. "0%" would misleadingly read as a bad result rather
   * than "no data yet". */
  displayOverride?: string;
}) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? value : 0);

  useEffect(() => {
    let raf = 0;
    if (reduce) { raf = requestAnimationFrame(() => setShown(value)); return () => cancelAnimationFrame(raf); }
    const start = performance.now();
    const dur = 700;
    const tick = (t: number) => {
      const p = Math.min((t - start) / dur, 1);
      setShown(Math.round(value * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, reduce]);

  return (
    <GlassCard className={accent ? "g-kpi g-kpi--accent" : "g-kpi"}>
      <div className="g-kpi__top">
        <span className="g-kpi__label">{label}</span>
        {icon && <span className="g-kpi__icon">{icon}</span>}
      </div>
      <div className="g-kpi__value">{displayOverride ?? `${shown.toLocaleString()}${suffix}`}</div>
    </GlassCard>
  );
}

/* ── Page transition wrapper ────────────────────────────────────────────── */

export function PageTransition({ children, pageKey }: { children: ReactNode; pageKey: string }) {
  const reduce = useReducedMotion();
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={pageKey}
        style={{ height: "100%", minHeight: 0, display: "flex", flexDirection: "column" }}
        initial={reduce ? { opacity: 0 } : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={reduce ? { opacity: 0 } : { opacity: 0, y: -6 }}
        transition={{ duration: reduce ? 0.05 : 0.18, ease: [0.4, 0, 0.2, 1] }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

/* ── Section header ─────────────────────────────────────────────────────── */

export function SectionHeader({ title, sub, actions }: {
  title: string; sub?: string; actions?: ReactNode;
}) {
  return (
    <div className="g-section-header">
      <div>
        <h2 className="g-section-header__title">{title}</h2>
        {sub && <p className="g-section-header__sub">{sub}</p>}
      </div>
      {actions && <div className="g-section-header__actions">{actions}</div>}
    </div>
  );
}
