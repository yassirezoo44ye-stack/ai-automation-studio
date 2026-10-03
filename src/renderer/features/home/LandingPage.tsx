/**
 * Flow Landing Page — dynamic, alive, premium SaaS experience.
 *
 * Architecture:
 *  - Full-screen marketing page for unauthenticated visitors
 *  - Auth modal overlay (sign in / register) triggered by CTAs
 *  - IntersectionObserver-based scroll reveals (no heavy animation libs)
 *  - CSS keyframe animations for live system simulations
 *  - framer-motion for hero entrance only
 *  - RTL / Arabic first-class via useLangContext
 *  - prefers-reduced-motion respected
 *
 * Sections (§):
 *  §1  Navbar
 *  §2  Hero + Live Workflow Panel
 *  §3  Live Terminal ticker
 *  §4  The Difference
 *  §5  AI Agents workforce
 *  §6  Workflow Builder mini-canvas
 *  §7  AgentOS command center
 *  §8  AI Gateway routing
 *  §9  Memory
 *  §10 Integrations ecosystem
 *  §11 How It Works (scroll-reactive)
 *  §12 Use Cases
 *  §13 Benefits
 *  §14 Security
 *  §15 Pricing
 *  §16 Final CTA
 *  §17 Footer
 */
import {
  useEffect, useRef, useState, useCallback, useMemo
} from "react";
import { useTranslation } from "react-i18next";
import { motion, AnimatePresence } from "framer-motion";
import { useLangContext } from "../../contexts/lang";
import { AuthPage } from "../auth/AuthPage";
import AxonLogo from "../../AxonLogo";

// ── Palette (dark landing theme) ─────────────────────────────────────────────
const C = {
  bg:        "#090909",
  surface:   "#131313",
  elevated:  "#1C1C1C",
  border:    "rgba(255,255,255,0.07)",
  borderHi:  "rgba(255,255,255,0.14)",
  pink:      "#FF1744",
  pinkDim:   "rgba(255,23,68,0.12)",
  pinkBorder:"rgba(255,23,68,0.28)",
  green:     "#00E676",
  greenDim:  "rgba(0,230,118,0.12)",
  blue:      "#2979FF",
  blueDim:   "rgba(41,121,255,0.12)",
  purple:    "#C051FF",
  purpleDim: "rgba(192,81,255,0.12)",
  cyan:      "#00E5FF",
  cyanDim:   "rgba(0,229,255,0.12)",
  yellow:    "#FFD740",
  yellowDim: "rgba(255,215,64,0.12)",
  t1:        "#FFFFFF",
  t2:        "rgba(255,255,255,0.80)",
  t3:        "rgba(255,255,255,0.50)",
  t4:        "rgba(255,255,255,0.30)",
  t5:        "rgba(255,255,255,0.18)",
};

// ── Utilities ─────────────────────────────────────────────────────────────────

/** Observe entrance of a ref with IntersectionObserver */
function useInView(threshold = 0.15) {
  const ref  = useRef<HTMLDivElement>(null);
  const [vis, setVis] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setVis(true); obs.disconnect(); } },
      { threshold }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);
  return { ref, vis };
}

/** Shared section wrapper with fade-up reveal */
function Section({
  children, id, style,
}: { children: React.ReactNode; id?: string; style?: React.CSSProperties }) {
  const { ref, vis } = useInView();
  return (
    <section
      id={id}
      ref={ref}
      style={{
        padding: "80px 24px",
        maxWidth: 1100,
        margin: "0 auto",
        opacity: vis ? 1 : 0,
        transform: vis ? "none" : "translateY(32px)",
        transition: "opacity 0.6s ease, transform 0.6s ease",
        ...style,
      }}
    >
      {children}
    </section>
  );
}

/** Eyebrow badge */
function Badge({ label, color = C.pink }: { label: string; color?: string }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      fontSize: 11, fontWeight: 700, letterSpacing: "0.1em",
      textTransform: "uppercase", color,
      background: color + "18", border: `1px solid ${color}28`,
      borderRadius: 99, padding: "4px 12px", marginBottom: 16,
    }}>
      <span style={{
        width: 5, height: 5, borderRadius: "50%", background: color,
        animation: "ldPulse 2s ease infinite",
        display: "inline-block",
      }} />
      {label}
    </span>
  );
}

/** Section headline */
function Headline({
  text, sub, center, accentWord,
}: { text: string; sub?: string; center?: boolean; accentWord?: string }) {
  let rendered: React.ReactNode = text;
  if (accentWord && text.includes(accentWord)) {
    const idx = text.indexOf(accentWord);
    rendered = (
      <>
        {text.slice(0, idx)}
        <span style={{ color: C.pink }}>{accentWord}</span>
        {text.slice(idx + accentWord.length)}
      </>
    );
  }
  return (
    <div style={{ textAlign: center ? "center" : undefined, marginBottom: sub ? 12 : 40 }}>
      <h2 style={{
        fontSize: "clamp(26px, 4vw, 40px)", fontWeight: 800, color: C.t1,
        margin: "0 0 12px", lineHeight: 1.2, letterSpacing: "-0.02em",
      }}>
        {rendered}
      </h2>
      {sub && (
        <p style={{ fontSize: "clamp(14px, 2vw, 17px)", color: C.t3, maxWidth: 540, margin: center ? "0 auto" : "0", lineHeight: 1.7 }}>
          {sub}
        </p>
      )}
    </div>
  );
}

// ══ §2  Hero — Live Workflow Panel ════════════════════════════════════════════

const NODE_STATES = ["pending", "active", "done"] as const;
type NS = typeof NODE_STATES[number];

function LiveWorkflowPanel({ steps }: { steps: string[] }) {
  const [step, setStep] = useState(0);
  const [phase, setPhase] = useState<NS>("active");
  const [completed, setCompleted] = useState<boolean[]>(steps.map(() => false));

  useEffect(() => {
    const run = () => {
      setPhase("active");
      const t1 = setTimeout(() => {
        setCompleted(prev => {
          const n = [...prev];
          n[step] = true;
          return n;
        });
        setPhase("done");
        const t2 = setTimeout(() => {
          setStep(s => {
            const next = (s + 1) % steps.length;
            if (next === 0) setCompleted(steps.map(() => false));
            return next;
          });
        }, 600);
        return () => clearTimeout(t2);
      }, 1200);
      return () => clearTimeout(t1);
    };
    const cleanup = run();
    return cleanup;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, steps.length]);

  const icons = ["⚡", "🤖", "⚙", "✉", "🔔"];

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: 16, padding: "20px 24px",
      minWidth: 280, maxWidth: 360,
      boxShadow: "0 8px 48px rgba(0,0,0,0.6)",
      position: "relative", overflow: "hidden",
    }}>
      {/* Glow */}
      <div style={{
        position: "absolute", top: -60, insetInlineEnd: -40,
        width: 180, height: 180, borderRadius: "50%",
        background: "radial-gradient(circle, rgba(255,23,68,0.15) 0%, transparent 70%)",
        pointerEvents: "none",
      }} />

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 20 }}>
        <span style={{
          width: 8, height: 8, borderRadius: "50%", background: C.green,
          animation: "ldPulse 2s ease infinite",
          flexShrink: 0,
        }} />
        <span style={{ fontSize: 12, fontWeight: 700, color: C.t2, letterSpacing: "0.05em" }}>
          Flow · Live Run
        </span>
        <span style={{
          marginInlineStart: "auto", fontSize: 9, fontWeight: 700,
          textTransform: "uppercase", letterSpacing: "0.08em",
          color: C.green, background: C.greenDim, padding: "2px 8px", borderRadius: 99,
        }}>LIVE</span>
      </div>

      {/* Steps */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {steps.map((s, i) => {
          const isDone  = completed[i];
          const isActive = i === step && !isDone;
          const isPend  = i > step || (i === step && phase === "pending");
          const nodeColor = isDone ? C.green : isActive ? C.pink : C.t5;

          return (
            <div key={i}>
              <div style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "8px 10px", borderRadius: 8,
                background: isActive ? C.pinkDim : "transparent",
                border: `1px solid ${isActive ? C.pinkBorder : "transparent"}`,
                transition: "all 0.3s ease",
              }}>
                <span style={{ fontSize: 14, flexShrink: 0, opacity: isPend ? 0.3 : 1 }}>
                  {icons[i] ?? "⚙"}
                </span>
                <span style={{
                  flex: 1, fontSize: 12, fontWeight: 600,
                  color: isDone ? C.t2 : isActive ? C.t1 : C.t4,
                  transition: "color 0.3s",
                }}>
                  {s}
                </span>
                <span style={{ fontSize: 14, flexShrink: 0, transition: "all 0.3s" }}>
                  {isDone  ? <span style={{ color: C.green }}>✓</span>
                  : isActive ? <span style={{
                      display: "inline-block",
                      width: 8, height: 8, borderRadius: "50%",
                      background: C.pink,
                      animation: "ldBlink 0.8s ease infinite",
                    }} />
                  : <span style={{ color: C.t5 }}>○</span>}
                </span>
              </div>
              {/* Connector line */}
              {i < steps.length - 1 && (
                <div style={{
                  width: 1, height: 10, background: nodeColor,
                  marginInlineStart: 20, opacity: 0.4, transition: "background 0.3s",
                }} />
              )}
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div style={{
        marginTop: 16, paddingTop: 12, borderTop: `1px solid ${C.border}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: C.pink, textTransform: "uppercase", letterSpacing: "0.08em" }}>
          RUNNING
        </span>
        <span style={{ fontSize: 10, color: C.t4 }}>
          {completed.filter(Boolean).length}/{steps.length}
        </span>
      </div>
    </div>
  );
}

// ══ §3  Live Terminal ═════════════════════════════════════════════════════════

function LiveTerminal({ tasks }: { tasks: string[] }) {
  const [current, setCurrent] = useState(1);
  const [done, setDone] = useState([true, false, false, false, false]);

  useEffect(() => {
    const id = setInterval(() => {
      setCurrent(prev => {
        const next = (prev + 1) % tasks.length;
        setDone(d => {
          const n = [...d];
          n[prev] = true;
          if (next === 0) return tasks.map(() => false);
          return n;
        });
        return next;
      });
    }, 1500);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks.length]);

  return (
    <div style={{
      background: C.surface, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: "16px 20px", minWidth: 260, maxWidth: 340,
    }}>
      <div style={{
        fontSize: 10, fontWeight: 700, color: C.pink,
        textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 12,
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <span style={{
          width: 6, height: 6, borderRadius: "50%", background: C.pink,
          animation: "ldPulse 1s ease infinite",
        }} />
        LIVE RUN
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {tasks.map((task, i) => {
          const isDone    = done[i];
          const isActive  = i === current;
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{
                fontSize: 11, flexShrink: 0,
                color: isDone ? C.green : isActive ? C.pink : C.t5,
                transition: "color 0.3s",
              }}>
                {isDone ? "✓" : isActive ? "●" : "○"}
              </span>
              <span style={{
                fontSize: 12,
                color: isDone ? C.t3 : isActive ? C.t1 : C.t4,
                fontWeight: isActive ? 600 : 400,
                transition: "color 0.3s",
              }}>
                {task}{isActive ? "..." : ""}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ══ §4  The Difference ═══════════════════════════════════════════════════════

function DifferenceSection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const stages = ((): string[] => {
    try { return JSON.parse(JSON.stringify(t("difference.stages"))) as string[]; }
    catch { return []; }
  })();
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (!vis) return;
    const id = setInterval(() => setActive(a => (a + 1) % 5), 900);
    return () => clearInterval(id);
  }, [vis]);

  return (
    <section id="difference" ref={ref} style={{
      padding: "80px 24px",
      maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <Badge label={t("difference.badge")} color={C.purple} />
        <Headline text={t("difference.headline")} sub={t("difference.sub")} center />
      </div>

      {/* Prompt card */}
      <div style={{ maxWidth: 680, margin: "0 auto 40px", position: "relative" }}>
        <div style={{
          background: C.elevated, border: `1px solid ${C.purpleDim}`,
          borderRadius: 12, padding: "14px 18px",
          display: "flex", alignItems: "flex-start", gap: 12,
        }}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>💬</span>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: C.purple, marginBottom: 4, letterSpacing: "0.06em" }}>
              PROMPT
            </div>
            <div style={{ fontSize: 14, color: C.t2, lineHeight: 1.6 }}>
              {t("difference.prompt")}
            </div>
          </div>
        </div>
      </div>

      {/* Stages */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        gap: 0, flexWrap: "wrap", maxWidth: 680, margin: "0 auto",
      }}>
        {stages.map((stage, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center" }}>
            <div style={{
              padding: "10px 20px",
              background: i === active ? C.purple : i < active ? C.purpleDim : C.surface,
              border: `1px solid ${i === active ? C.purple : i < active ? C.purpleDim : C.border}`,
              borderRadius: 99,
              fontSize: 13, fontWeight: 700,
              color: i === active ? "#fff" : i < active ? C.purple : C.t4,
              transition: "all 0.4s ease",
              transform: i === active ? "scale(1.08)" : "none",
              whiteSpace: "nowrap",
            }}>
              {i < active && <span style={{ marginInlineEnd: 4 }}>✓</span>}
              {stage}
            </div>
            {i < stages.length - 1 && (
              <div style={{
                width: 24, height: 1,
                background: i < active ? C.purple : C.border,
                transition: "background 0.4s",
                flexShrink: 0,
              }} />
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// ══ §5  AI Agents workforce ═══════════════════════════════════════════════════

function AgentsSection({ t, onCta }: { t: (k: string) => string; onCta: () => void }) {
  const { ref, vis } = useInView();
  const nodes = t("agents.nodes") as unknown as string[];
  const statuses = t("agents.statuses") as unknown as string[];
  const [hovered, setHovered] = useState<number | null>(null);
  const colors = [C.blue, C.pink, C.purple, C.cyan, C.green];

  // adjacency for the ring layout: 0=top center, 1=left, 2=center, 3=right, 4=bottom
  const positions = [
    { top: "8%",  left: "50%",  transform: "translate(-50%,0)"    },
    { top: "35%", left: "8%",   transform: "translate(0,-50%)"    },
    { top: "35%", left: "50%",  transform: "translate(-50%,-50%)" },
    { top: "35%", left: "92%",  transform: "translate(-100%,-50%)" },
    { top: "70%", left: "50%",  transform: "translate(-50%,0)"    },
  ];

  return (
    <section id="agents" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48, alignItems: "center" }}>
        <div>
          <Badge label={t("agents.badge")} color={C.blue} />
          <Headline text={t("agents.headline")} sub={t("agents.sub")} />
          <button
            onClick={onCta}
            style={{
              padding: "12px 28px", borderRadius: 10, border: "none",
              background: `linear-gradient(135deg, ${C.blue}, ${C.purple})`,
              color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer",
              boxShadow: `0 4px 24px ${C.blueDim}`,
              transition: "transform 0.15s, box-shadow 0.15s",
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-2px)"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.transform = "none"; }}
          >
            {t("nav.getStarted")} →
          </button>
        </div>

        {/* Network visualization */}
        <div style={{ position: "relative", height: 280 }}>
          {/* Connection lines */}
          <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} viewBox="0 0 400 280">
            {/* 0→2 */}<line x1="200" y1="30" x2="200" y2="110" stroke={hovered === 0 || hovered === 2 ? C.blue : C.border} strokeWidth="1.5" strokeDasharray="4 4">
              <animate attributeName="stroke-dashoffset" from="8" to="0" dur="1s" repeatCount="indefinite"/>
            </line>
            {/* 1→2 */}<line x1="40" y1="108" x2="200" y2="108" stroke={hovered === 1 || hovered === 2 ? C.pink : C.border} strokeWidth="1.5" strokeDasharray="4 4">
              <animate attributeName="stroke-dashoffset" from="8" to="0" dur="0.8s" repeatCount="indefinite"/>
            </line>
            {/* 2→3 */}<line x1="200" y1="108" x2="360" y2="108" stroke={hovered === 2 || hovered === 3 ? C.purple : C.border} strokeWidth="1.5" strokeDasharray="4 4">
              <animate attributeName="stroke-dashoffset" from="8" to="0" dur="1.2s" repeatCount="indefinite"/>
            </line>
            {/* 2→4 */}<line x1="200" y1="110" x2="200" y2="210" stroke={hovered === 2 || hovered === 4 ? C.cyan : C.border} strokeWidth="1.5" strokeDasharray="4 4">
              <animate attributeName="stroke-dashoffset" from="8" to="0" dur="0.9s" repeatCount="indefinite"/>
            </line>
          </svg>

          {/* Nodes */}
          {(Array.isArray(nodes) ? nodes : []).map((name, i) => (
            <div
              key={i}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              style={{
                position: "absolute",
                ...positions[i],
                display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
                cursor: "default",
              }}
            >
              <div style={{
                width: 52, height: 52, borderRadius: 14,
                background: hovered === i ? colors[i] : C.elevated,
                border: `1.5px solid ${hovered === i ? colors[i] : colors[i] + "40"}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                transition: "all 0.25s ease",
                boxShadow: hovered === i ? `0 0 20px ${colors[i]}40` : "none",
              }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                  stroke={hovered === i ? "#fff" : colors[i]} strokeWidth="1.8">
                  <circle cx="12" cy="12" r="3"/>
                  <path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3"/>
                </svg>
              </div>
              <div style={{ fontSize: 10, fontWeight: 700, color: hovered === i ? C.t1 : C.t3, whiteSpace: "nowrap", textAlign: "center" }}>
                {name}
              </div>
              <div style={{
                fontSize: 9, color: colors[i], fontWeight: 600,
                animation: `ldPulse ${1 + i * 0.3}s ease infinite`,
              }}>
                {Array.isArray(statuses) ? statuses[i] : ""}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ══ §6  Workflow Builder mini-canvas ══════════════════════════════════════════

function WorkflowSection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const nodes = t("workflow.nodes") as unknown as string[];
  const [signal, setSignal] = useState(0);

  useEffect(() => {
    if (!vis) return;
    const id = setInterval(() => setSignal(s => (s + 1) % (Array.isArray(nodes) ? nodes.length : 7)), 700);
    return () => clearInterval(id);
  }, [vis, nodes]);

  const WORKFLOW = Array.isArray(nodes) ? nodes : [];
  const nodeColors = [C.pink, C.blue, C.purple, C.yellow, C.green, C.cyan, C.pink];

  return (
    <section id="workflow" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <Badge label={t("workflow.badge")} color={C.cyan} />
        <Headline text={t("workflow.headline")} sub={t("workflow.sub")} center />
      </div>

      {/* Mini workflow canvas */}
      <div style={{
        background: C.surface, border: `1px solid ${C.border}`,
        borderRadius: 16, padding: "32px 24px",
        display: "flex", alignItems: "center", justifyContent: "center",
        flexWrap: "wrap", gap: 0, overflow: "hidden", position: "relative",
      }}>
        {/* Grid background */}
        <div style={{
          position: "absolute", inset: 0,
          backgroundImage: `radial-gradient(${C.border} 1px, transparent 1px)`,
          backgroundSize: "24px 24px",
          opacity: 0.6,
        }} />

        <div style={{
          position: "relative", display: "flex", alignItems: "center",
          flexWrap: "wrap", gap: 0, justifyContent: "center",
        }}>
          {WORKFLOW.map((node, i) => {
            const isActive = i === signal;
            const isDone   = i < signal;
            return (
              <div key={i} style={{ display: "flex", alignItems: "center" }}>
                {/* Node */}
                <div style={{
                  display: "flex", flexDirection: "column", alignItems: "center",
                  gap: 6, padding: "10px 14px",
                  background: isActive ? nodeColors[i] + "22" : C.elevated,
                  border: `1.5px solid ${isActive ? nodeColors[i] : isDone ? nodeColors[i] + "55" : C.border}`,
                  borderRadius: 10,
                  transition: "all 0.35s ease",
                  boxShadow: isActive ? `0 0 16px ${nodeColors[i]}40` : "none",
                  minWidth: 64,
                  transform: isActive ? "scale(1.08)" : "scale(1)",
                }}>
                  <div style={{ width: 8, height: 8, borderRadius: "50%", background: isActive ? nodeColors[i] : isDone ? C.green : C.t5, transition: "background 0.35s" }} />
                  <span style={{ fontSize: 11, fontWeight: 700, color: isActive ? C.t1 : C.t3, whiteSpace: "nowrap", transition: "color 0.35s" }}>
                    {node}
                  </span>
                </div>

                {/* Arrow */}
                {i < WORKFLOW.length - 1 && (
                  <div style={{
                    width: 20, height: 1,
                    background: isDone ? nodeColors[i] : C.border,
                    transition: "background 0.35s", flexShrink: 0,
                    position: "relative",
                  }}>
                    <div style={{
                      position: "absolute", insetInlineEnd: 0, top: "50%",
                      transform: "translateY(-50%)",
                      borderStyle: "solid",
                      borderWidth: "3px 0 3px 6px",
                      borderColor: `transparent transparent transparent ${isDone ? nodeColors[i] : C.border}`,
                      transition: "border-color 0.35s",
                    }} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ══ §7  AgentOS command center ════════════════════════════════════════════════

function AgentOSSection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const metrics = t("agentos.metrics") as unknown as { label: string; value: string }[];
  const activity = t("agentos.activity") as unknown as { name: string; status: string }[];
  const metricColors = [C.pink, C.blue, C.green, C.yellow];

  return (
    <section id="agentos" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <Badge label={t("agentos.badge")} color={C.green} />
        <Headline text={t("agentos.headline")} sub={t("agentos.sub")} center />
      </div>

      <div style={{
        background: C.surface, border: `1px solid ${C.border}`,
        borderRadius: 16, padding: "28px 24px",
        maxWidth: 720, margin: "0 auto",
      }}>
        {/* Metrics row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 24 }}>
          {(Array.isArray(metrics) ? metrics : []).map((m, i) => (
            <div key={i} style={{
              background: C.elevated, borderRadius: 10, padding: "12px",
              border: `1px solid ${metricColors[i]}22`,
              textAlign: "center",
            }}>
              <div style={{ fontSize: "clamp(20px,3vw,28px)", fontWeight: 800, color: metricColors[i], lineHeight: 1 }}>
                {m.value}
              </div>
              <div style={{ fontSize: 10, color: C.t4, marginTop: 4, fontWeight: 600 }}>
                {m.label}
              </div>
            </div>
          ))}
        </div>

        {/* Activity list */}
        <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 16 }}>
          {(Array.isArray(activity) ? activity : []).map((a, i) => {
            const isRunning = i === 0 || i === 2;
            const dotColor  = isRunning ? C.green : C.t5;
            return (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "8px 0",
                borderBottom: i < (Array.isArray(activity) ? activity.length - 1 : 0) ? `1px solid ${C.border}` : "none",
              }}>
                <span style={{
                  width: 7, height: 7, borderRadius: "50%", background: dotColor,
                  flexShrink: 0, animation: isRunning ? "ldPulse 1.5s ease infinite" : "none",
                }} />
                <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: C.t2 }}>{a.name}</span>
                <span style={{
                  fontSize: 11, fontWeight: 700, color: isRunning ? C.green : C.t4,
                  padding: "2px 8px", borderRadius: 99,
                  background: isRunning ? C.greenDim : "transparent",
                }}>
                  {a.status}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ══ §8  AI Gateway ════════════════════════════════════════════════════════════

function GatewaySection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const labels = t("gateway.labels") as unknown as string[];
  const modelColors = [C.blue, C.pink, C.purple];
  const modelNames  = ["GPT", "Claude", "Gemini"];
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (!vis) return;
    const id = setInterval(() => setActive(a => (a + 1) % 3), 1000);
    return () => clearInterval(id);
  }, [vis]);

  return (
    <section id="gateway" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48, alignItems: "center" }}>
        {/* Visualization */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
          {/* Request bubble */}
          <div style={{
            padding: "10px 20px", borderRadius: 99,
            background: C.elevated, border: `1px solid ${C.border}`,
            fontSize: 12, fontWeight: 700, color: C.t2,
          }}>
            {t("gateway.request")}
          </div>

          {/* Arrow down */}
          <div style={{ width: 1, height: 24, background: C.pink, position: "relative" }}>
            <div style={{
              position: "absolute", bottom: 0, left: "50%", transform: "translate(-50%,50%)",
              borderStyle: "solid", borderWidth: "6px 4px 0",
              borderColor: `${C.pink} transparent transparent`,
            }} />
          </div>

          {/* Gateway box */}
          <div style={{
            padding: "12px 28px", borderRadius: 12,
            background: `linear-gradient(135deg, ${C.pinkDim}, ${C.purpleDim})`,
            border: `1.5px solid ${C.pinkBorder}`,
            fontSize: 13, fontWeight: 800, color: C.t1,
            boxShadow: `0 0 24px ${C.pinkDim}`,
          }}>
            {t("gateway.gateway")}
          </div>

          {/* Fan out arrows + models */}
          <div style={{ display: "flex", gap: 32, alignItems: "flex-start", position: "relative" }}>
            {/* Lines */}
            <svg style={{ position: "absolute", top: -24, left: "50%", transform: "translateX(-50%)", pointerEvents: "none" }}
              width="280" height="28">
              <line x1="140" y1="0" x2="40"  y2="28" stroke={active === 0 ? C.blue   : C.border} strokeWidth="1.5" strokeDasharray="3 3">
                <animate attributeName="stroke-dashoffset" from="6" to="0" dur="0.5s" repeatCount="indefinite"/>
              </line>
              <line x1="140" y1="0" x2="140" y2="28" stroke={active === 1 ? C.pink   : C.border} strokeWidth="1.5" strokeDasharray="3 3">
                <animate attributeName="stroke-dashoffset" from="6" to="0" dur="0.5s" repeatCount="indefinite"/>
              </line>
              <line x1="140" y1="0" x2="240" y2="28" stroke={active === 2 ? C.purple : C.border} strokeWidth="1.5" strokeDasharray="3 3">
                <animate attributeName="stroke-dashoffset" from="6" to="0" dur="0.5s" repeatCount="indefinite"/>
              </line>
            </svg>

            {modelNames.map((m, i) => (
              <div key={i} style={{
                display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
              }}>
                <div style={{
                  padding: "8px 16px", borderRadius: 10,
                  background: active === i ? modelColors[i] + "22" : C.elevated,
                  border: `1.5px solid ${active === i ? modelColors[i] : C.border}`,
                  fontSize: 12, fontWeight: 700,
                  color: active === i ? C.t1 : C.t4,
                  transition: "all 0.3s ease",
                  boxShadow: active === i ? `0 0 12px ${modelColors[i]}40` : "none",
                }}>
                  {m}
                </div>
                {Array.isArray(labels) && labels[i] && (
                  <span style={{ fontSize: 9, fontWeight: 700, color: modelColors[i], letterSpacing: "0.08em" }}>
                    {labels[i]}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div>
          <Badge label={t("gateway.badge")} color={C.pink} />
          <Headline text={t("gateway.headline")} sub={t("gateway.sub")} />
        </div>
      </div>
    </section>
  );
}

// ══ §9  Memory ════════════════════════════════════════════════════════════════

function MemorySection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const flow = t("memory.flow") as unknown as string[];
  const chips = ["user_prefs", "team_data", "workflow_ctx", "prev_results", "org_rules"];
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!vis) return;
    const id = setInterval(() => setTick(x => x + 1), 800);
    return () => clearInterval(id);
  }, [vis]);

  return (
    <section id="memory" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48, alignItems: "center" }}>
        <div>
          <Badge label={t("memory.badge")} color={C.cyan} />
          <Headline text={t("memory.headline")} sub={t("memory.sub")} />
        </div>

        {/* Memory visualization */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
          {(Array.isArray(flow) ? flow : []).map((stage, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", width: "100%" }}>
              <div style={{
                padding: "10px 20px", borderRadius: 10,
                background: i === 1 ? C.cyanDim : C.elevated,
                border: `1.5px solid ${i === 1 ? C.cyan + "50" : C.border}`,
                fontSize: 13, fontWeight: 700,
                color: i === 1 ? C.cyan : C.t2,
                width: "100%", textAlign: "center",
                position: "relative", overflow: "hidden",
              }}>
                {stage}
                {/* Floating context chips inside memory box */}
                {i === 1 && (
                  <div style={{
                    display: "flex", gap: 4, justifyContent: "center", marginTop: 8, flexWrap: "wrap",
                  }}>
                    {chips.map((c, ci) => (
                      <span key={ci} style={{
                        fontSize: 9, padding: "2px 6px", borderRadius: 99,
                        background: C.cyan + "22", border: `1px solid ${C.cyan}30`,
                        color: C.cyan,
                        animation: `ldFloat ${1.5 + ci * 0.3}s ease-in-out infinite`,
                        animationDelay: `${ci * 0.2}s`,
                        opacity: ci === (tick % 5) ? 1 : 0.4,
                        transition: "opacity 0.5s",
                      }}>
                        {c}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {i < (Array.isArray(flow) ? flow.length - 1 : 0) && (
                <div style={{ width: 1, height: 16, background: C.border, opacity: 0.5 }} />
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ══ §10 Integrations ══════════════════════════════════════════════════════════

function IntegrationsSection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const integNodes = t("integrations.nodes") as unknown as string[];
  const nodeColors = [C.pink, C.blue, C.green, C.yellow, C.purple, C.cyan, C.pink];
  const nodeAngles = [0, 52, 104, 156, 208, 260, 312];
  const R = 130;

  return (
    <section id="integrations" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <Badge label={t("integrations.badge")} color={C.yellow} />
        <Headline text={t("integrations.headline")} sub={t("integrations.sub")} center />
      </div>

      <div style={{ display: "flex", justifyContent: "center" }}>
        <div style={{ position: "relative", width: 320, height: 320 }}>
          {/* Center */}
          <div style={{
            position: "absolute", top: "50%", left: "50%",
            transform: "translate(-50%,-50%)",
            width: 70, height: 70, borderRadius: "50%",
            background: `linear-gradient(135deg, ${C.pink}, ${C.purple})`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 12, fontWeight: 800, color: "#fff",
            boxShadow: `0 0 32px ${C.pinkDim}`,
            zIndex: 1,
          }}>
            {t("integrations.center")}
          </div>

          {/* Nodes */}
          {(Array.isArray(integNodes) ? integNodes : []).map((name, i) => {
            const rad = (nodeAngles[i] - 90) * (Math.PI / 180);
            const x   = 160 + R * Math.cos(rad);
            const y   = 160 + R * Math.sin(rad);
            return (
              <div key={i}>
                {/* Pulse line */}
                <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
                  <line
                    x1="160" y1="160"
                    x2={x} y2={y}
                    stroke={nodeColors[i]}
                    strokeWidth="1"
                    strokeDasharray="3 3"
                    opacity="0.35"
                  >
                    <animate attributeName="stroke-dashoffset" from="6" to="0" dur={`${0.8 + i * 0.15}s`} repeatCount="indefinite"/>
                  </line>
                  {/* Traveling dot */}
                  <circle r="3" fill={nodeColors[i]} opacity="0.7">
                    <animateMotion dur={`${1.2 + i * 0.2}s`} repeatCount="indefinite" path={`M 160 160 L ${x} ${y}`}/>
                  </circle>
                </svg>

                {/* Node pill */}
                <div style={{
                  position: "absolute",
                  left: x, top: y,
                  transform: "translate(-50%,-50%)",
                  padding: "5px 12px", borderRadius: 99,
                  background: C.elevated,
                  border: `1px solid ${nodeColors[i]}40`,
                  fontSize: 11, fontWeight: 700, color: nodeColors[i],
                  whiteSpace: "nowrap",
                  zIndex: 1,
                }}>
                  {name}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ══ §11 How It Works ═════════════════════════════════════════════════════════

function HowItWorksSection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const [activeStep, setActiveStep] = useState(0);
  const steps = t("howItWorks.steps") as unknown as { n: string; title: string; desc: string }[];
  const stepColors = [C.pink, C.blue, C.purple, C.green, C.cyan];
  const stepIcons = [
    <svg key="i" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>,
    <svg key="b" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>,
    <svg key="r" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>,
    <svg key="m" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>,
    <svg key="s" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>,
  ];

  useEffect(() => {
    if (!vis) return;
    const id = setInterval(() => setActiveStep(s => (s + 1) % (Array.isArray(steps) ? steps.length : 5)), 2000);
    return () => clearInterval(id);
  }, [vis, steps]);

  return (
    <section id="how-it-works" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <Badge label={t("howItWorks.badge")} color={C.green} />
        <Headline text={t("howItWorks.headline")} center />
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 12,
      }}>
        {(Array.isArray(steps) ? steps : []).map((step, i) => (
          <div
            key={i}
            onMouseEnter={() => setActiveStep(i)}
            style={{
              background: i === activeStep ? stepColors[i] + "16" : C.surface,
              border: `1.5px solid ${i === activeStep ? stepColors[i] : i < activeStep ? stepColors[i] + "40" : C.border}`,
              borderRadius: 14, padding: "20px 16px",
              transition: "all 0.35s ease",
              cursor: "default",
            }}
          >
            <div style={{
              width: 44, height: 44, borderRadius: 12, marginBottom: 12,
              background: i === activeStep ? stepColors[i] : C.elevated,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: i === activeStep ? "#fff" : stepColors[i],
              transition: "all 0.35s ease",
            }}>
              {stepIcons[i]}
            </div>
            <div style={{ fontSize: 11, fontWeight: 800, color: stepColors[i], marginBottom: 4, letterSpacing: "0.06em" }}>
              {step.n}
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: C.t1, marginBottom: 6 }}>
              {step.title}
            </div>
            <div style={{ fontSize: 12, color: C.t3, lineHeight: 1.6 }}>
              {step.desc}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ══ §12 Use Cases ════════════════════════════════════════════════════════════

function UseCasesSection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const items = t("useCases.items") as unknown as { id: string; title: string; nodes: string[] }[];
  const [hovered, setHovered] = useState<number | null>(null);
  const [active, setActive] = useState<{ case: number; node: number } | null>(null);
  const caseColors = [C.pink, C.blue, C.purple];

  useEffect(() => {
    if (hovered === null) { setActive(null); return; }
    const nodes = Array.isArray(items) && items[hovered] ? items[hovered].nodes : [];
    let i = 0;
    const id = setInterval(() => {
      setActive({ case: hovered, node: i % nodes.length });
      i++;
    }, 500);
    return () => clearInterval(id);
  }, [hovered, items]);

  return (
    <section id="use-cases" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <Badge label={t("useCases.badge")} color={C.purple} />
        <Headline text={t("useCases.headline")} center />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
        {(Array.isArray(items) ? items : []).map((item, ci) => (
          <div
            key={item.id}
            onMouseEnter={() => setHovered(ci)}
            onMouseLeave={() => setHovered(null)}
            style={{
              background: C.surface, border: `1.5px solid ${hovered === ci ? caseColors[ci] + "60" : C.border}`,
              borderRadius: 14, padding: "20px",
              transition: "border-color 0.25s",
              cursor: "default",
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 700, color: caseColors[ci], marginBottom: 16 }}>
              {item.title}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 0, flexWrap: "wrap" }}>
              {item.nodes.map((node, ni) => {
                const isActive = active?.case === ci && active.node === ni;
                return (
                  <div key={ni} style={{ display: "flex", alignItems: "center" }}>
                    <span style={{
                      fontSize: 11, fontWeight: 700,
                      padding: "4px 10px", borderRadius: 99,
                      background: isActive ? caseColors[ci] + "22" : "transparent",
                      border: `1px solid ${isActive ? caseColors[ci] : "transparent"}`,
                      color: isActive ? C.t1 : C.t4,
                      transition: "all 0.25s", whiteSpace: "nowrap",
                    }}>
                      {node}
                    </span>
                    {ni < item.nodes.length - 1 && (
                      <span style={{
                        fontSize: 10, color: isActive ? caseColors[ci] : C.t5, margin: "0 2px",
                        transition: "color 0.25s",
                      }}>→</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ══ §13 Benefits ═════════════════════════════════════════════════════════════

function BenefitsSection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const items = t("benefits.items") as unknown as { label: string; value: string }[];
  const metricColors = [C.green, C.blue, C.pink];

  return (
    <section id="benefits" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <Badge label={t("benefits.badge")} color={C.green} />
        <Headline text={t("benefits.headline")} sub={t("benefits.sub")} center />
      </div>

      {/* Before → Flow → After */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        gap: 16, flexWrap: "wrap", marginBottom: 48, maxWidth: 700, margin: "0 auto 48px",
      }}>
        {/* Before */}
        <div style={{ flex: 1, minWidth: 160, textAlign: "center" }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: C.t4, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.08em" }}>
            {t("benefits.before")}
          </div>
          <div style={{ height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${C.t5}, ${C.t4})`, marginBottom: 4 }} />
          <div style={{ height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${C.t5}, ${C.t4})`, width: "90%", marginBottom: 4 }} />
          <div style={{ height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${C.t5}, ${C.t4})`, width: "85%", marginBottom: 4 }} />
          <div style={{ height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${C.t5}, ${C.t4})`, width: "80%" }} />
        </div>

        {/* Arrow */}
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
          flexShrink: 0,
        }}>
          <div style={{
            padding: "8px 20px", borderRadius: 10,
            background: `linear-gradient(135deg, ${C.pink}, ${C.purple})`,
            fontSize: 13, fontWeight: 800, color: "#fff",
            boxShadow: `0 0 24px ${C.pinkDim}`,
          }}>FLOW</div>
          <span style={{ fontSize: 20, color: C.pink }}>↓</span>
        </div>

        {/* After */}
        <div style={{ flex: 1, minWidth: 160, textAlign: "center" }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: C.green, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.08em" }}>
            {t("benefits.after")}
          </div>
          <div style={{
            height: 8, borderRadius: 4,
            background: `linear-gradient(90deg, ${C.green + "80"}, ${C.green})`,
            width: "25%", marginBottom: 4,
          }} />
          <div style={{
            height: 8, borderRadius: 4,
            background: `linear-gradient(90deg, ${C.green + "80"}, ${C.green})`,
            width: "22%",
          }} />
        </div>
      </div>

      {/* Metric chips */}
      <div style={{ display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
        {(Array.isArray(items) ? items : []).map((item, i) => (
          <div key={i} style={{
            background: C.surface, border: `1.5px solid ${metricColors[i]}30`,
            borderRadius: 14, padding: "20px 28px", textAlign: "center",
            minWidth: 140,
          }}>
            <div style={{ fontSize: 36, fontWeight: 800, color: metricColors[i], lineHeight: 1 }}>
              {item.value}
            </div>
            <div style={{ fontSize: 12, color: C.t3, marginTop: 6 }}>{item.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ══ §14 Security ═════════════════════════════════════════════════════════════

function SecuritySection({ t }: { t: (k: string) => string }) {
  const { ref, vis } = useInView();
  const layers = t("security.layers") as unknown as string[];
  const layerColors = [C.blue, C.blue, C.purple, C.pink, C.green];

  return (
    <section id="security" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48, alignItems: "center" }}>
        <div>
          <Badge label={t("security.badge")} color={C.blue} />
          <Headline text={t("security.headline")} sub={t("security.sub")} />
        </div>

        {/* Layer stack */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3, maxWidth: 360 }}>
          {(Array.isArray(layers) ? layers : []).map((layer, i) => (
            <div key={i} style={{
              display: "flex", alignItems: "center", gap: 12,
              padding: "12px 16px", borderRadius: 10,
              background: C.elevated,
              border: `1px solid ${layerColors[i]}30`,
              borderBottom: i < (Array.isArray(layers) ? layers.length - 1 : 0)
                ? `1px solid ${layerColors[i]}30` : `1px solid ${layerColors[i]}30`,
              paddingInlineStart: `${16 + i * 10}px`,
              animation: vis ? `ldSlideIn 0.4s ease ${i * 0.08}s both` : "none",
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: 8, flexShrink: 0,
                background: layerColors[i] + "18",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={layerColors[i]} strokeWidth="2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
              </div>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.t2 }}>{layer}</span>
              <span style={{ marginInlineStart: "auto", fontSize: 14, color: C.green }}>✓</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ══ §15 Pricing ══════════════════════════════════════════════════════════════

function PricingSection({ t, onCta }: { t: (k: string) => string; onCta: () => void }) {
  const { ref, vis } = useInView();
  const plans = t("pricing.plans") as unknown as {
    id: string; name: string; price: string; period: string;
    desc: string; cta: string; badge?: string;
    features: string[];
  }[];

  return (
    <section id="pricing" ref={ref} style={{
      padding: "80px 24px", maxWidth: 1100, margin: "0 auto",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.6s ease, transform 0.6s ease",
    }}>
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <Badge label={t("pricing.badge")} color={C.pink} />
        <Headline text={t("pricing.headline")} center />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, alignItems: "start" }}>
        {(Array.isArray(plans) ? plans : []).map((plan) => {
          const isPro = plan.id === "pro";
          return (
            <div key={plan.id} style={{
              background: isPro ? `linear-gradient(180deg, ${C.pinkDim}, ${C.surface})` : C.surface,
              border: `1.5px solid ${isPro ? C.pink : C.border}`,
              borderRadius: 16, padding: "28px 24px",
              position: "relative",
              transform: isPro ? "scale(1.04)" : "none",
              boxShadow: isPro ? `0 0 40px ${C.pinkDim}` : "none",
              transition: "transform 0.2s ease, box-shadow 0.2s ease",
            }}
              onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.transform = isPro ? "scale(1.06)" : "translateY(-3px)"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.transform = isPro ? "scale(1.04)" : "none"; }}
            >
              {plan.badge && (
                <div style={{
                  position: "absolute", top: -12, left: "50%", transform: "translateX(-50%)",
                  background: C.pink, color: "#fff",
                  fontSize: 10, fontWeight: 800, padding: "4px 12px", borderRadius: 99,
                  letterSpacing: "0.06em", textTransform: "uppercase", whiteSpace: "nowrap",
                }}>
                  {plan.badge}
                </div>
              )}

              <div style={{ fontSize: 16, fontWeight: 800, color: C.t1, marginBottom: 4 }}>{plan.name}</div>
              <div style={{ fontSize: 11, color: C.t4, marginBottom: 16 }}>{plan.desc}</div>

              <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginBottom: 20 }}>
                <span style={{ fontSize: 36, fontWeight: 800, color: isPro ? C.pink : C.t1, lineHeight: 1 }}>{plan.price}</span>
                <span style={{ fontSize: 13, color: C.t4 }}>{plan.period}</span>
              </div>

              <button
                onClick={onCta}
                style={{
                  width: "100%", padding: "11px", borderRadius: 10, border: "none",
                  background: isPro ? `linear-gradient(135deg, ${C.pink}, ${C.purple})` : C.elevated,
                  color: isPro ? "#fff" : C.t2,
                  fontSize: 13, fontWeight: 700, cursor: "pointer",
                  marginBottom: 20,
                  transition: "opacity 0.15s",
                }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.opacity = "0.85"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.opacity = "1"; }}
              >
                {plan.cta}
              </button>

              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {plan.features.map(f => (
                  <div key={f} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ color: C.green, fontSize: 12, flexShrink: 0 }}>✓</span>
                    <span style={{ fontSize: 12, color: C.t3 }}>{f}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ══ §16 Final CTA ════════════════════════════════════════════════════════════

function FinalCTASection({ t, onCta }: { t: (k: string) => string; onCta: () => void }) {
  const { ref, vis } = useInView();
  const flow = t("finalCta.flow") as unknown as string[];

  return (
    <section ref={ref} style={{
      padding: "100px 24px",
      textAlign: "center",
      opacity: vis ? 1 : 0, transform: vis ? "none" : "translateY(32px)",
      transition: "opacity 0.8s ease, transform 0.8s ease",
      position: "relative",
    }}>
      {/* Glow */}
      <div style={{
        position: "absolute", top: "50%", left: "50%",
        transform: "translate(-50%,-50%)",
        width: 600, height: 300, borderRadius: "50%",
        background: "radial-gradient(ellipse, rgba(255,23,68,0.08) 0%, transparent 70%)",
        pointerEvents: "none",
      }} />

      {/* Flow chain */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, marginBottom: 32, flexWrap: "wrap" }}>
        {(Array.isArray(flow) ? flow : []).map((step, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              padding: "6px 16px", borderRadius: 99,
              background: i === 1 ? `linear-gradient(135deg, ${C.pink}, ${C.purple})` : C.surface,
              border: `1px solid ${i === 1 ? C.pink : C.border}`,
              fontSize: 12, fontWeight: 800, color: i === 1 ? "#fff" : C.t3,
              letterSpacing: "0.08em", textTransform: "uppercase",
            }}>
              {step}
            </div>
            {i < (Array.isArray(flow) ? flow.length - 1 : 0) && (
              <span style={{ color: C.t5, fontSize: 16 }}>↓</span>
            )}
          </div>
        ))}
      </div>

      <h2 style={{
        fontSize: "clamp(24px,4vw,44px)", fontWeight: 800, color: C.t1,
        lineHeight: 1.2, letterSpacing: "-0.02em",
        maxWidth: 700, margin: "0 auto 16px",
      }}>
        {t("finalCta.headline")}
      </h2>
      <p style={{ fontSize: 17, color: C.t3, maxWidth: 500, margin: "0 auto 40px", lineHeight: 1.7 }}>
        {t("finalCta.sub")}
      </p>

      <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
        <button
          onClick={onCta}
          style={{
            padding: "14px 36px", borderRadius: 12, border: "none",
            background: `linear-gradient(135deg, ${C.pink}, ${C.purple})`,
            color: "#fff", fontSize: 15, fontWeight: 800, cursor: "pointer",
            boxShadow: `0 6px 32px ${C.pinkDim}`,
            transition: "transform 0.15s, box-shadow 0.15s",
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-2px)";
            (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 10px 40px ${C.pink}40`;
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.transform = "none";
            (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 6px 32px ${C.pinkDim}`;
          }}
        >
          {t("finalCta.cta1")}
        </button>
        <button
          onClick={onCta}
          style={{
            padding: "14px 28px", borderRadius: 12,
            border: `1px solid ${C.border}`,
            background: "transparent", color: C.t2,
            fontSize: 15, fontWeight: 700, cursor: "pointer",
            transition: "border-color 0.15s",
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = C.pink; }}
          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = C.border; }}
        >
          {t("finalCta.cta2")}
        </button>
      </div>
    </section>
  );
}

// ══ Auth Modal ════════════════════════════════════════════════════════════════

function AuthModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const fn = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          key="auth-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={onClose}
          style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.75)", backdropFilter: "blur(6px)",
            zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center",
            padding: 24,
          }}
        >
          <motion.div
            key="auth-card"
            initial={{ opacity: 0, scale: 0.94, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.94, y: 20 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            onClick={e => e.stopPropagation()}
            style={{ width: "100%", maxWidth: 440, borderRadius: 20, overflow: "hidden" }}
          >
            {/* Close button */}
            <div style={{ position: "relative" }}>
              <button
                onClick={onClose}
                style={{
                  position: "absolute", top: 12, insetInlineEnd: 12, zIndex: 10,
                  width: 28, height: 28, borderRadius: "50%",
                  background: "rgba(255,255,255,0.1)", border: "none",
                  color: "#fff", fontSize: 14, cursor: "pointer",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}
              >
                ×
              </button>
              <AuthPage />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ══ Main Landing Page ════════════════════════════════════════════════════════

export function LandingPage() {
  const { t } = useTranslation("landing");
  const { lang, toggleLang } = useLangContext();
  const [authOpen, setAuthOpen] = useState(false);
  const openAuth = useCallback(() => setAuthOpen(true), []);
  const closeAuth = useCallback(() => setAuthOpen(false), []);

  const heroSteps  = useMemo(() => t("hero.steps")  as unknown as string[], [t]);
  const termTasks  = useMemo(() => t("terminal.tasks") as unknown as string[], [t]);

  return (
    <div style={{
      background: C.bg,
      color: C.t1,
      fontFamily: "var(--font-sans, 'Cairo', system-ui, sans-serif)",
      minHeight: "100dvh",
      overflowX: "hidden",
      position: "relative",
    }}>

      {/* Global keyframes */}
      <style>{`
        @keyframes ldPulse  { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.5;transform:scale(1.4)} }
        @keyframes ldBlink  { 0%,100%{opacity:1} 50%{opacity:0.2} }
        @keyframes ldFloat  { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-4px)} }
        @keyframes ldSpin   { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
        @keyframes ldSlideIn{ from{opacity:0;transform:translateX(-12px)} to{opacity:1;transform:none} }
        @keyframes ldGlow   { 0%,100%{box-shadow:0 0 20px rgba(255,23,68,0.2)} 50%{box-shadow:0 0 40px rgba(255,23,68,0.5)} }
        @keyframes ldScroll { 0%{transform:translateY(0)} 100%{transform:translateY(-50%)} }
        @media (prefers-reduced-motion: reduce) {
          * { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; }
        }

        /* ── Background grid ── */
        .ld-grid-bg {
          position: fixed; inset: 0; pointer-events: none; z-index: 0;
          background-image:
            radial-gradient(ellipse 80% 50% at 50% -10%, rgba(255,23,68,0.08) 0%, transparent 60%),
            linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
          background-size: auto, 48px 48px, 48px 48px;
        }
        /* ── Responsive ── */
        @media (max-width: 768px) {
          .ld-hero-grid  { grid-template-columns: 1fr !important; }
          .ld-two-col    { grid-template-columns: 1fr !important; }
          .ld-hide-mobile{ display: none !important; }
          .ld-agents-net { height: 200px !important; }
        }
        @media (max-width: 480px) {
          .ld-nav-links { display: none !important; }
        }
      `}</style>

      {/* Ambient grid bg */}
      <div className="ld-grid-bg" />

      {/* ── §1 Navbar ──────────────────────────────────────────────────────── */}
      <nav style={{
        position: "sticky", top: 0, zIndex: 100,
        background: `${C.bg}cc`,
        backdropFilter: "blur(12px)",
        borderBottom: `1px solid ${C.border}`,
        padding: "0 24px",
        height: 60, display: "flex", alignItems: "center",
        justifyContent: "space-between", gap: 16,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <AxonLogo size={32} />
          <span style={{ fontSize: 16, fontWeight: 800, color: C.t1, letterSpacing: "-0.02em" }}>Flow</span>
          <span style={{
            fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 99,
            background: C.pinkDim, border: `1px solid ${C.pinkBorder}`,
            color: C.pink, letterSpacing: "0.08em", textTransform: "uppercase",
          }}>AI</span>
        </div>

        {/* Nav links */}
        <div className="ld-nav-links" style={{ display: "flex", alignItems: "center", gap: 24 }}>
          {["product", "agents", "workflows", "pricing"].map(k => (
            <a key={k} href={`#${k}`} style={{
              fontSize: 13, fontWeight: 600, color: C.t3, textDecoration: "none",
              transition: "color 0.15s",
            }}
              onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.color = C.t1; }}
              onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.color = C.t3; }}
            >
              {t(`nav.${k}`)}
            </a>
          ))}
        </div>

        {/* Right actions */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Lang toggle */}
          <button
            onClick={toggleLang}
            style={{
              padding: "5px 10px", borderRadius: 8,
              border: `1px solid ${C.border}`,
              background: "transparent", color: C.t3,
              fontSize: 12, fontWeight: 700, cursor: "pointer",
              letterSpacing: "0.04em", transition: "border-color 0.15s, color 0.15s",
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = C.pink;
              (e.currentTarget as HTMLButtonElement).style.color = C.t1;
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = C.border;
              (e.currentTarget as HTMLButtonElement).style.color = C.t3;
            }}
          >
            {lang === "ar" ? "EN" : "عربي"}
          </button>

          <button
            onClick={openAuth}
            style={{
              padding: "7px 16px", borderRadius: 8,
              border: `1px solid ${C.border}`,
              background: "transparent", color: C.t2,
              fontSize: 13, fontWeight: 600, cursor: "pointer",
              transition: "border-color 0.15s",
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = C.borderHi; }}
            onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = C.border; }}
          >
            {t("nav.signIn")}
          </button>
          <button
            onClick={openAuth}
            style={{
              padding: "7px 16px", borderRadius: 8, border: "none",
              background: `linear-gradient(135deg, ${C.pink}, ${C.purple})`,
              color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer",
              boxShadow: `0 2px 12px ${C.pinkDim}`,
              transition: "opacity 0.15s",
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.opacity = "0.85"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.opacity = "1"; }}
          >
            {t("nav.getStarted")}
          </button>
        </div>
      </nav>

      {/* Page content */}
      <div style={{ position: "relative", zIndex: 1 }}>

        {/* ── §2 Hero ──────────────────────────────────────────────────────── */}
        <section style={{ padding: "80px 24px 60px", maxWidth: 1100, margin: "0 auto" }}>
          <div
            className="ld-hero-grid"
            style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48, alignItems: "center" }}
          >
            {/* Left: copy */}
            <motion.div
              initial={{ opacity: 0, x: lang === "ar" ? 40 : -40 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
            >
              <div style={{ marginBottom: 16 }}>
                <Badge label={t("hero.badge")} color={C.pink} />
              </div>
              <h1 style={{
                fontSize: "clamp(36px,6vw,64px)", fontWeight: 900, color: C.t1,
                margin: "0 0 8px", lineHeight: 1.1, letterSpacing: "-0.03em",
              }}>
                {t("hero.headline1")}
                <br />
                <span style={{
                  background: `linear-gradient(135deg, ${C.pink}, ${C.purple})`,
                  WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
                }}>
                  {t("hero.headline2")}
                </span>
              </h1>
              <p style={{
                fontSize: "clamp(14px,2vw,18px)", color: C.t3, lineHeight: 1.75,
                maxWidth: 480, marginBottom: 32,
              }}>
                {t("hero.sub")}
              </p>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                <button
                  onClick={openAuth}
                  style={{
                    padding: "13px 32px", borderRadius: 12, border: "none",
                    background: `linear-gradient(135deg, ${C.pink}, ${C.purple})`,
                    color: "#fff", fontSize: 15, fontWeight: 800, cursor: "pointer",
                    boxShadow: `0 6px 28px ${C.pinkDim}`,
                    transition: "transform 0.15s, box-shadow 0.15s",
                    animation: "ldGlow 3s ease infinite",
                  }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-2px)";
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 10px 36px ${C.pink}50`;
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLButtonElement).style.transform = "none";
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 6px 28px ${C.pinkDim}`;
                  }}
                >
                  {t("hero.cta1")} →
                </button>
                <button
                  onClick={openAuth}
                  style={{
                    padding: "13px 24px", borderRadius: 12,
                    border: `1px solid ${C.border}`,
                    background: "transparent", color: C.t2,
                    fontSize: 15, fontWeight: 600, cursor: "pointer",
                    transition: "border-color 0.15s",
                    display: "flex", alignItems: "center", gap: 8,
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = C.borderHi; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = C.border; }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"/>
                    <polygon points="10 8 16 12 10 16 10 8"/>
                  </svg>
                  {t("hero.cta2")}
                </button>
              </div>
            </motion.div>

            {/* Right: Live Workflow Panel + Terminal */}
            <motion.div
              className="ld-hide-mobile"
              initial={{ opacity: 0, x: lang === "ar" ? -40 : 40 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.7, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
              style={{ display: "flex", flexDirection: "column", gap: 16, alignItems: "flex-end" }}
            >
              <LiveWorkflowPanel steps={Array.isArray(heroSteps) ? heroSteps : []} />
              <LiveTerminal tasks={Array.isArray(termTasks) ? termTasks : []} />
            </motion.div>
          </div>
        </section>

        {/* Divider glow */}
        <div style={{
          height: 1, background: `linear-gradient(90deg, transparent, ${C.pink}40, ${C.purple}40, transparent)`,
          maxWidth: 800, margin: "0 auto",
        }} />

        {/* ── §4 The Difference ────────────────────────────────────────────── */}
        <DifferenceSection t={t} />

        {/* ── §5 AI Agents ─────────────────────────────────────────────────── */}
        <AgentsSection t={t} onCta={openAuth} />

        {/* Divider */}
        <div style={{
          height: 1, background: `linear-gradient(90deg, transparent, ${C.blue}30, transparent)`,
          maxWidth: 600, margin: "0 auto",
        }} />

        {/* ── §6 Workflow Builder ───────────────────────────────────────────── */}
        <WorkflowSection t={t} />

        {/* ── §7 AgentOS ────────────────────────────────────────────────────── */}
        <AgentOSSection t={t} />

        {/* ── §8 AI Gateway ─────────────────────────────────────────────────── */}
        <GatewaySection t={t} />

        {/* ── §9 Memory ─────────────────────────────────────────────────────── */}
        <MemorySection t={t} />

        {/* ── §10 Integrations ──────────────────────────────────────────────── */}
        <IntegrationsSection t={t} />

        {/* Divider */}
        <div style={{
          height: 1, background: `linear-gradient(90deg, transparent, ${C.purple}30, transparent)`,
          maxWidth: 600, margin: "0 auto",
        }} />

        {/* ── §11 How It Works ─────────────────────────────────────────────── */}
        <HowItWorksSection t={t} />

        {/* ── §12 Use Cases ────────────────────────────────────────────────── */}
        <UseCasesSection t={t} />

        {/* ── §13 Benefits ─────────────────────────────────────────────────── */}
        <BenefitsSection t={t} />

        {/* ── §14 Security ─────────────────────────────────────────────────── */}
        <SecuritySection t={t} />

        {/* ── §15 Pricing ──────────────────────────────────────────────────── */}
        <PricingSection t={t} onCta={openAuth} />

        {/* ── §16 Final CTA ────────────────────────────────────────────────── */}
        <FinalCTASection t={t} onCta={openAuth} />

        {/* ── §17 Footer ───────────────────────────────────────────────────── */}
        <footer style={{
          borderTop: `1px solid ${C.border}`,
          padding: "32px 24px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          flexWrap: "wrap", gap: 12,
          maxWidth: 1100, margin: "0 auto",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <AxonLogo size={24} />
            <span style={{ fontSize: 13, fontWeight: 700, color: C.t2 }}>Flow</span>
            <span style={{ fontSize: 12, color: C.t4 }}>— {t("footer.tagline")}</span>
          </div>
          <span style={{ fontSize: 12, color: C.t5 }}>{t("footer.copy")}</span>
        </footer>
      </div>

      {/* ── Auth Modal ─────────────────────────────────────────────────────── */}
      <AuthModal open={authOpen} onClose={closeAuth} />
    </div>
  );
}
