/**
 * BuildPlanPanel — shows an AI-generated build plan for user review.
 *
 * Rendered between "user submits prompt" and "build starts".
 * The user can Approve (triggers build) or request Modifications
 * (edits the plan text and re-generates, or just tweaks the prompt).
 *
 * All plan data comes from the real /api/build/plan backend response —
 * nothing here is mock or simulated.
 */
import { useState } from "react";

export type BuildPlan = {
  name: string;
  description: string;
  tech_stack: { frontend?: string; backend?: string; database?: string };
  pages: string[];
  database_tables: string[];
  api_routes: string[];
  agents: string[];
  workflows: string[];
  integrations: string[];
  estimated_files: number;
  complexity: "simple" | "moderate" | "complex";
};

interface Props {
  plan: BuildPlan;
  prompt: string;
  onApprove: () => void;
  onModify: (newPrompt: string) => void;
  onCancel: () => void;
  isRefining: boolean;
}

type PlanSection = {
  label: string;
  icon: string;
  items: string[];
  color: string;
  show: boolean;
};

const COMPLEXITY_COLOR = {
  simple: "var(--green)",
  moderate: "var(--yellow)",
  complex: "var(--accent)",
};

export function BuildPlanPanel({ plan, prompt, onApprove, onModify, onCancel, isRefining }: Props) {
  const [editing, setEditing] = useState(false);
  const [editedPrompt, setEditedPrompt] = useState(prompt);

  const sections: PlanSection[] = [
    { label: "Pages",      icon: "📄", items: plan.pages,           color: "var(--blue)",   show: plan.pages.length > 0 },
    { label: "Database",   icon: "🗄️",  items: plan.database_tables, color: "var(--teal)",   show: plan.database_tables.length > 0 },
    { label: "API Routes", icon: "🔌", items: plan.api_routes,      color: "var(--accent)", show: plan.api_routes.length > 0 },
    { label: "Agents",     icon: "🤖", items: plan.agents,          color: "var(--purple, var(--accent))", show: plan.agents.length > 0 },
    { label: "Workflows",  icon: "⚡", items: plan.workflows,       color: "var(--yellow)", show: plan.workflows.length > 0 },
    { label: "Integrations",icon:"🔗", items: plan.integrations,    color: "var(--green)",  show: plan.integrations.length > 0 },
  ].filter(s => s.show);

  return (
    <div style={{
      position: "absolute", inset: 0,
      background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 20, padding: 24,
    }}>
      <div style={{
        background: "var(--bg-surface)", borderRadius: 20, padding: "28px 32px",
        maxWidth: 620, width: "100%", maxHeight: "85vh", overflowY: "auto",
        boxShadow: "0 24px 64px rgba(0,0,0,0.4)",
        border: "1px solid var(--b1)",
      }}>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", color: "var(--accent)", textTransform: "uppercase", marginBottom: 6 }}>
              ✦ AI Build Plan
            </div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "var(--t1)", letterSpacing: "-0.3px" }}>
              {plan.name}
            </div>
            <div style={{ fontSize: 13, color: "var(--t4)", marginTop: 4, lineHeight: 1.5 }}>
              {plan.description}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6, marginLeft: 16, flexShrink: 0 }}>
            <span style={{
              fontSize: 10, fontWeight: 700, padding: "3px 10px", borderRadius: 99,
              background: `${COMPLEXITY_COLOR[plan.complexity ?? "moderate"]}18`,
              color: COMPLEXITY_COLOR[plan.complexity ?? "moderate"],
              border: `1px solid ${COMPLEXITY_COLOR[plan.complexity ?? "moderate"]}40`,
              textTransform: "capitalize",
            }}>
              {plan.complexity}
            </span>
            <span style={{ fontSize: 10, color: "var(--t5)", fontWeight: 500 }}>
              ~{plan.estimated_files} files
            </span>
          </div>
        </div>

        {/* Tech stack badges */}
        {plan.tech_stack && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 20 }}>
            {Object.entries(plan.tech_stack).map(([role, tech]) => tech && (
              <span key={role} style={{
                fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 6,
                background: "var(--bg-card)", border: "1px solid var(--b1)", color: "var(--t3)",
              }}>
                {tech}
              </span>
            ))}
          </div>
        )}

        {/* Plan tree */}
        <div style={{
          background: "var(--bg-base)", borderRadius: 12,
          border: "1px solid var(--b1)", padding: "16px 20px", marginBottom: 20,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 12 }}>
            Build Plan
          </div>
          <div style={{ fontFamily: "monospace", fontSize: 12 }}>
            <div style={{ color: "var(--t2)", fontWeight: 600, marginBottom: 4 }}>
              {plan.name}
            </div>
            {sections.map((s, si) => (
              <div key={s.label} style={{ marginLeft: 8 }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 3 }}>
                  <span style={{ color: "var(--t5)", minWidth: 20, flexShrink: 0 }}>
                    {si === sections.length - 1 ? "└──" : "├──"}
                  </span>
                  <span style={{ color: s.color, fontWeight: 600 }}>{s.icon} {s.label}</span>
                </div>
                {s.items.map((item, ii) => (
                  <div key={ii} style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 2, marginLeft: 28 }}>
                    <span style={{ color: "var(--t5)", minWidth: 20, flexShrink: 0 }}>
                      {ii === s.items.length - 1 ? "└─" : "├─"}
                    </span>
                    <span style={{ color: "var(--t3)", lineHeight: 1.4, fontFamily: "inherit", fontSize: 12 }}>{item}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>

        {/* Modify prompt */}
        {editing && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t4)", marginBottom: 6 }}>
              Modify your prompt — the plan will be regenerated
            </div>
            <textarea
              value={editedPrompt}
              onChange={e => setEditedPrompt(e.target.value)}
              rows={3}
              style={{
                width: "100%", padding: "10px 12px", fontSize: 13, lineHeight: 1.6,
                borderRadius: 8, border: "1px solid var(--accent)", outline: "none",
                background: "var(--bg-card)", color: "var(--t1)", resize: "vertical",
                fontFamily: "inherit", boxSizing: "border-box",
              }}
              autoFocus
            />
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={onCancel}
            disabled={isRefining}
            style={{
              padding: "9px 16px", borderRadius: 10, border: "1px solid var(--b1)",
              background: "transparent", color: "var(--t4)", fontSize: 13,
              cursor: "pointer", fontWeight: 500,
            }}
          >
            Cancel
          </button>
          {!editing ? (
            <button
              onClick={() => setEditing(true)}
              disabled={isRefining}
              style={{
                flex: 1, padding: "9px 0", borderRadius: 10, border: "1px solid var(--b2)",
                background: "transparent", color: "var(--t2)", fontSize: 13,
                cursor: "pointer", fontWeight: 500, transition: "border-color 0.12s",
              }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--accent)")}
              onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--b2)")}
            >
              Modify Plan
            </button>
          ) : (
            <button
              onClick={() => { setEditing(false); onModify(editedPrompt); }}
              disabled={isRefining || !editedPrompt.trim()}
              style={{
                flex: 1, padding: "9px 0", borderRadius: 10,
                border: "1px solid var(--b2)",
                background: "var(--bg-card)",
                color: isRefining ? "var(--t5)" : "var(--t2)", fontSize: 13,
                cursor: isRefining ? "not-allowed" : "pointer", fontWeight: 500,
              }}
            >
              {isRefining ? "Regenerating…" : "Regenerate Plan"}
            </button>
          )}
          <button
            onClick={onApprove}
            disabled={isRefining}
            style={{
              flex: 1, padding: "9px 0", borderRadius: 10, border: "none",
              background: isRefining
                ? "var(--bg-card)"
                : "linear-gradient(135deg, var(--accent) 0%, var(--teal) 100%)",
              color: isRefining ? "var(--t5)" : "white",
              fontSize: 13, cursor: isRefining ? "not-allowed" : "pointer",
              fontWeight: 700, boxShadow: isRefining ? "none" : "0 2px 12px rgba(110,50,224,0.35)",
              transition: "all 0.12s",
            }}
          >
            ✓ Approve Plan
          </button>
        </div>
      </div>
    </div>
  );
}
