import type { FactoryPhase } from "../types/saasFactory.types";

interface Props {
  phase: FactoryPhase;
  label: string;
  description: string;
  status: "pending" | "active" | "done" | "failed";
  output?: Record<string, unknown>;
}

const STATUS_ICON: Record<string, string> = {
  pending: "○",
  active:  "◎",
  done:    "✓",
  failed:  "✕",
};

const STATUS_COLOR: Record<string, string> = {
  pending: "var(--t4)",
  active:  "var(--accent)",
  done:    "#10b981",
  failed:  "#ef4444",
};

function OutputSnippet({ output }: { output: Record<string, unknown> }) {
  const keys = Object.keys(output).slice(0, 3);
  if (!keys.length) return null;
  return (
    <div className="sf-phase-output">
      {keys.map(k => {
        const v = output[k];
        const display =
          typeof v === "string" ? v.slice(0, 60) :
          Array.isArray(v) ? `[${v.length} items]` :
          typeof v === "object" ? "{…}" : String(v);
        return (
          <span key={k} className="sf-phase-output__pill">
            <span className="sf-phase-output__key">{k}</span>
            <span className="sf-phase-output__val">{display}</span>
          </span>
        );
      })}
    </div>
  );
}

export function PhaseCard({ label, description, status, output }: Props) {
  const icon  = STATUS_ICON[status];
  const color = STATUS_COLOR[status];
  return (
    <div className={`sf-phase-card sf-phase-card--${status}`}>
      <div className="sf-phase-card__header">
        <span className="sf-phase-card__icon" style={{ color }}>{icon}</span>
        <span className="sf-phase-card__label">{label}</span>
        {status === "active" && (
          <span className="sf-phase-card__pulse" aria-label="running" />
        )}
      </div>
      <p className="sf-phase-card__desc">{description}</p>
      {status === "done" && output && <OutputSnippet output={output} />}
    </div>
  );
}
