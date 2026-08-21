/**
 * PublishCenterPage — deploy and manage app environments.
 * Data: typed adapters (no backend endpoint yet; ready to wire to deploy API).
 * RTL-first: logical CSS properties throughout.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

/* ── Types ──────────────────────────────────────────────────────────────── */
type EnvStatus = "live" | "staging" | "offline";

interface Environment {
  id: string;
  name: string;
  status: EnvStatus;
  url: string;
  version: string;
  lastDeploy: string;
  region: string;
}

interface DeployEvent {
  id: string;
  envId: string;
  version: string;
  status: "success" | "failed" | "deploying";
  triggeredBy: string;
  time: string;
  duration: string;
}

/* ── Static data (typed adapter) ─────────────────────────────────────────── */
const ENVIRONMENTS: Environment[] = [
  { id: "prod",    name: "Production",  status: "live",    url: "https://app.flow.co",       version: "v2.4.1",  lastDeploy: "2h ago",   region: "us-east-1"  },
  { id: "staging", name: "Staging",     status: "staging", url: "https://staging.flow.co",   version: "v2.5.0",  lastDeploy: "45m ago",  region: "us-east-1"  },
  { id: "preview", name: "Preview",     status: "live",    url: "https://preview.flow.co",   version: "v2.5.1",  lastDeploy: "10m ago",  region: "eu-west-1"  },
  { id: "dev",     name: "Development", status: "offline", url: "https://dev.flow.co",       version: "v2.5.1",  lastDeploy: "5d ago",   region: "us-west-2"  },
];

const DEPLOYS: DeployEvent[] = [
  { id: "d1", envId: "preview", version: "v2.5.1", status: "success",   triggeredBy: "push",   time: "10m ago",  duration: "1m 42s" },
  { id: "d2", envId: "staging", version: "v2.5.0", status: "success",   triggeredBy: "push",   time: "45m ago",  duration: "1m 55s" },
  { id: "d3", envId: "prod",    version: "v2.4.1", status: "success",   triggeredBy: "manual", time: "2h ago",   duration: "2m 10s" },
  { id: "d4", envId: "staging", version: "v2.4.9", status: "failed",    triggeredBy: "push",   time: "3h ago",   duration: "0m 48s" },
  { id: "d5", envId: "prod",    version: "v2.4.0", status: "success",   triggeredBy: "manual", time: "1d ago",   duration: "2m 03s" },
];

const ENV_STATUS: Record<EnvStatus, { color: string; label: string; dot: string }> = {
  live:    { color: "var(--green)",  label: "Live",    dot: "var(--green)"  },
  staging: { color: "var(--yellow)", label: "Staging", dot: "var(--yellow)" },
  offline: { color: "var(--t3)",     label: "Offline", dot: "var(--t3)"     },
};

const DEPLOY_STATUS: Record<DeployEvent["status"], { color: string; label: string }> = {
  success:   { color: "var(--green)",  label: "Success"   },
  failed:    { color: "var(--red)",    label: "Failed"    },
  deploying: { color: "var(--blue)",   label: "Deploying" },
};

/* ── Page ─────────────────────────────────────────────────────────────── */
export function PublishCenterPage() {
  useTranslation("common");
  const [selected, setSelected] = useState<string>("prod");
  const [deploying, setDeploying] = useState<string | null>(null);

  const env      = ENVIRONMENTS.find(e => e.id === selected) ?? ENVIRONMENTS[0];
  const envDeploys = DEPLOYS.filter(d => d.envId === selected);

  const handleDeploy = (envId: string) => {
    setDeploying(envId);
    setTimeout(() => setDeploying(null), 2500);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", background: "var(--bg-base)", color: "var(--t1)" }}>
      {/* Header */}
      <div style={{ padding: "24px 28px 0", borderBlockEnd: "1px solid var(--b1)", background: "var(--bg-surface)", flexShrink: 0 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 4px", color: "var(--t1)" }}>Publish Center</h1>
        <p style={{ fontSize: 13, color: "var(--t3)", margin: "0 0 20px" }}>Deploy and manage your app environments</p>
      </div>

      {/* 3-column layout */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "220px 1fr 280px", overflow: "hidden" }}>

        {/* Column 1: Environments list */}
        <div style={{ borderInlineEnd: "1px solid var(--b1)", overflowY: "auto", padding: "16px 0" }}>
          <div style={{ paddingInline: 16, paddingBlockEnd: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--t3)" }}>Environments</span>
          </div>
          {ENVIRONMENTS.map(e => {
            const st = ENV_STATUS[e.status];
            const isActive = e.id === selected;
            return (
              <button
                key={e.id}
                onClick={() => setSelected(e.id)}
                style={{ width: "100%", display: "flex", gap: 10, alignItems: "center", padding: "10px 16px", background: isActive ? "var(--accent-dim)" : "transparent", border: "none", cursor: "pointer", textAlign: "start", transition: "background .12s" }}
              >
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: st.dot, flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: isActive ? 600 : 500, color: isActive ? "var(--accent)" : "var(--t1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.name}</div>
                  <div style={{ fontSize: 11, color: "var(--t3)" }}>{e.version}</div>
                </div>
              </button>
            );
          })}
          <div style={{ paddingInline: 16, paddingBlockStart: 12 }}>
            <button style={{ width: "100%", padding: "8px 0", fontSize: 12, fontWeight: 600, background: "var(--accent)", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}>
              + New Environment
            </button>
          </div>
        </div>

        {/* Column 2: Deploy history */}
        <div style={{ overflowY: "auto", padding: "20px 24px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBlockEnd: 20 }}>
            <div>
              <h2 style={{ fontSize: 15, fontWeight: 700, color: "var(--t1)", margin: 0 }}>{env.name}</h2>
              <a href={env.url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "var(--accent)", textDecoration: "none" }}>{env.url}</a>
            </div>
            <button
              onClick={() => handleDeploy(env.id)}
              disabled={deploying === env.id}
              style={{ padding: "8px 18px", fontSize: 13, fontWeight: 600, background: "var(--accent)", color: "#fff", border: "none", borderRadius: 8, cursor: deploying === env.id ? "wait" : "pointer", opacity: deploying === env.id ? 0.7 : 1, transition: "opacity .15s" }}
            >
              {deploying === env.id ? "Deploying…" : "Deploy Now"}
            </button>
          </div>

          {/* Env stats */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBlockEnd: 24 }}>
            {[
              { label: "Status",       value: ENV_STATUS[env.status].label, color: ENV_STATUS[env.status].color },
              { label: "Version",      value: env.version,                  color: "var(--t1)"                  },
              { label: "Last Deploy",  value: env.lastDeploy,               color: "var(--t1)"                  },
            ].map(item => (
              <div key={item.label} style={{ background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 10, padding: "12px 14px" }}>
                <div style={{ fontSize: 11, color: "var(--t3)", fontWeight: 500, marginBlockEnd: 4 }}>{item.label}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: item.color }}>{item.value}</div>
              </div>
            ))}
          </div>

          {/* Deploy history */}
          <h3 style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--t3)", marginBlockEnd: 10 }}>Deploy History</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {envDeploys.length === 0 && (
              <div style={{ padding: "24px 0", textAlign: "center", color: "var(--t3)", fontSize: 13 }}>No deploys for this environment.</div>
            )}
            {envDeploys.map(d => {
              const ds = DEPLOY_STATUS[d.status];
              return (
                <div key={d.id} style={{ display: "flex", gap: 12, alignItems: "center", background: "var(--bg-surface)", border: "1px solid var(--b1)", borderRadius: 10, padding: "10px 14px" }}>
                  <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 20, background: ds.color + "22", color: ds.color, whiteSpace: "nowrap" }}>{ds.label}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", flex: 1 }}>{d.version}</span>
                  <span style={{ fontSize: 11, color: "var(--t3)" }}>via {d.triggeredBy}</span>
                  <span style={{ fontSize: 11, color: "var(--t3)" }}>{d.duration}</span>
                  <span style={{ fontSize: 11, color: "var(--t4)" }}>{d.time}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Column 3: Settings */}
        <div style={{ borderInlineStart: "1px solid var(--b1)", overflowY: "auto", padding: "20px 20px" }}>
          <h3 style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--t3)", margin: "0 0 16px" }}>Settings</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {[
              { label: "Environment Name", value: env.name },
              { label: "Region",           value: env.region },
              { label: "Custom Domain",    value: env.url },
            ].map(f => (
              <div key={f.label}>
                <label style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", display: "block", marginBlockEnd: 4 }}>{f.label}</label>
                <input defaultValue={f.value} style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", fontSize: 13, background: "var(--bg-input)", border: "1px solid var(--b1)", borderRadius: 8, color: "var(--t1)", outline: "none" }} />
              </div>
            ))}

            <div style={{ marginBlockStart: 4 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--t3)", marginBlockEnd: 8 }}>Build & Deploy</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {["Auto-deploy on push", "Run tests before deploy", "Notify on failure"].map(opt => (
                  <label key={opt} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                    <input type="checkbox" defaultChecked={opt !== "Notify on failure"} style={{ accentColor: "var(--accent)" }} />
                    <span style={{ fontSize: 12, color: "var(--t2)" }}>{opt}</span>
                  </label>
                ))}
              </div>
            </div>

            <button style={{ marginBlockStart: 8, width: "100%", padding: "9px 0", fontSize: 13, fontWeight: 600, background: "var(--accent)", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}>
              Save Settings
            </button>
            <button style={{ width: "100%", padding: "8px 0", fontSize: 12, fontWeight: 500, background: "transparent", color: "var(--red)", border: "1px solid var(--red-dim)", borderRadius: 8, cursor: "pointer" }}>
              Delete Environment
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
