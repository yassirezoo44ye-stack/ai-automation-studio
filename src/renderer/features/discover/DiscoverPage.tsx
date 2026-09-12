import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useOrg } from "../../contexts/OrgContext";
import { useAppContext } from "../../contexts/app";
import type { FlowCreation, CreationType } from "./types/creation.types";
import {
  fetchDiscoverFeed,
  fetchMyCreations,
  publishCreation,
  unpublishCreation,
  cloneCreation,
  deleteCreation,
} from "./services/discoverService";

// ── Type badge colours ─────────────────────────────────────────────────────────

const TYPE_COLORS: Record<CreationType, string> = {
  APP:             "var(--accent)",
  AGENT:           "var(--teal)",
  WORKFLOW:        "#8b5cf6",
  AUTOMATION:      "#f59e0b",
  TEMPLATE:        "#10b981",
  DEVICE_WORKFLOW: "#6366f1",
};

const NON_CLONEABLE: CreationType[] = ["DEVICE_WORKFLOW", "AGENT"];

// ── Sub-components ─────────────────────────────────────────────────────────────

function TypeBadge({ type }: { type: CreationType }) {
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 700, letterSpacing: "0.05em",
      textTransform: "uppercase", padding: "2px 7px", borderRadius: 99,
      background: `${TYPE_COLORS[type]}22`,
      color: TYPE_COLORS[type],
      border: `1px solid ${TYPE_COLORS[type]}44`,
      flexShrink: 0,
    }}>
      {type.replace("_", " ")}
    </span>
  );
}

function VisibilityChip({ visibility }: { visibility: "private" | "public" }) {
  const { t } = useTranslation("discover");
  return (
    <span style={{
      fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 99,
      background: visibility === "public" ? "#10b98122" : "var(--b1)",
      color:      visibility === "public" ? "#10b981"   : "var(--t5)",
      border:     `1px solid ${visibility === "public" ? "#10b98144" : "var(--b2)"}`,
      flexShrink: 0,
    }}>
      {t(`card.${visibility}`)}
    </span>
  );
}

// ── Creation Detail Side Panel ─────────────────────────────────────────────────

interface DetailPanelProps {
  creation: FlowCreation;
  orgId: string | null;
  onClose: () => void;
  onAction: (action: string, id: string) => Promise<void>;
  isMine: boolean;
}

function DetailPanel({ creation: c, orgId, onClose, onAction, isMine }: DetailPanelProps) {
  const { t } = useTranslation("discover");
  const { setPage } = useAppContext();
  const [busy, setBusy] = useState<string | null>(null);

  const handleTry = () => {
    // Frontend-only routing to existing page — no new execution path
    if (c.type === "APP" || c.type === "AGENT")       { setPage("app-builder"); onClose(); }
    else if (c.type === "AUTOMATION" || c.type === "WORKFLOW") { setPage("automation"); onClose(); }
    else if (c.type === "TEMPLATE")                   { setPage("design"); onClose(); }
    else if (c.type === "DEVICE_WORKFLOW")             { setPage("devices"); onClose(); }
    else { onClose(); }
  };

  const handleAction = async (action: string) => {
    setBusy(action);
    try { await onAction(action, c.id); }
    finally { setBusy(null); }
  };

  const canClone = !NON_CLONEABLE.includes(c.type);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 500,
      display: "flex", justifyContent: "flex-end",
    }}>
      {/* Backdrop */}
      <div
        style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.4)" }}
        onClick={onClose}
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
        role="button"
        tabIndex={-1}
        aria-label="Close panel"
      />
      {/* Panel */}
      <div style={{
        position: "relative", zIndex: 1,
        width: 380, maxWidth: "100vw",
        background: "var(--bg-surface)",
        borderLeft: "1px solid var(--b1)",
        padding: "24px 20px",
        overflowY: "auto",
        display: "flex", flexDirection: "column", gap: 16,
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <TypeBadge type={c.type} />
              <VisibilityChip visibility={c.visibility} />
            </div>
            <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--t1)", margin: 0, lineHeight: 1.3 }}>
              {c.title}
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label={t("detail.close")}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: "var(--t4)", padding: 4, flexShrink: 0,
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        {/* Thumbnail */}
        {c.thumbnail_url && (
          <img
            src={c.thumbnail_url}
            alt={c.title}
            style={{ width: "100%", borderRadius: 8, objectFit: "cover", maxHeight: 160, border: "1px solid var(--b1)" }}
          />
        )}

        {/* Description */}
        {c.description && (
          <p style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.6, margin: 0 }}>
            {c.description}
          </p>
        )}

        {/* Meta */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 11, color: "var(--t5)" }}>
            {t("detail.created")}: {new Date(c.created_at).toLocaleDateString()}
          </div>
          {c.tags.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {c.tags.map(tag => (
                <span key={tag} style={{
                  fontSize: 10, padding: "2px 7px", borderRadius: 99,
                  background: "var(--b1)", color: "var(--t4)",
                  border: "1px solid var(--b2)",
                }}>{tag}</span>
              ))}
            </div>
          )}
        </div>

        {/* Primary actions */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
          <button
            onClick={handleTry}
            style={{
              background: "var(--accent)", color: "#fff",
              border: "none", borderRadius: 8,
              padding: "9px 16px", cursor: "pointer",
              fontWeight: 600, fontSize: 13, width: "100%",
            }}
          >
            {t("card.try")}
          </button>

          {canClone && orgId && (
            <button
              onClick={() => handleAction("clone")}
              disabled={busy === "clone"}
              style={{
                background: "var(--bg-input)", color: "var(--t2)",
                border: "1px solid var(--b2)", borderRadius: 8,
                padding: "9px 16px", cursor: busy === "clone" ? "default" : "pointer",
                fontWeight: 600, fontSize: 13, width: "100%",
                opacity: busy === "clone" ? 0.7 : 1,
              }}
            >
              {busy === "clone" ? t("actions.cloning") : t("card.clone")}
            </button>
          )}

          {isMine && (
            <>
              {c.visibility === "private" ? (
                <button
                  onClick={() => handleAction("publish")}
                  disabled={busy === "publish"}
                  style={{
                    background: "none", color: "var(--teal)",
                    border: "1px solid var(--teal)", borderRadius: 8,
                    padding: "8px 16px", cursor: busy === "publish" ? "default" : "pointer",
                    fontWeight: 600, fontSize: 13, width: "100%",
                    opacity: busy === "publish" ? 0.7 : 1,
                  }}
                >
                  {t("card.publish")}
                </button>
              ) : (
                <button
                  onClick={() => handleAction("unpublish")}
                  disabled={busy === "unpublish"}
                  style={{
                    background: "none", color: "var(--t4)",
                    border: "1px solid var(--b2)", borderRadius: 8,
                    padding: "8px 16px", cursor: busy === "unpublish" ? "default" : "pointer",
                    fontWeight: 600, fontSize: 13, width: "100%",
                    opacity: busy === "unpublish" ? 0.7 : 1,
                  }}
                >
                  {t("card.unpublish")}
                </button>
              )}
              <button
                onClick={() => handleAction("delete")}
                disabled={busy === "delete"}
                style={{
                  background: "none", color: "var(--red, #ef4444)",
                  border: "1px solid var(--red, #ef4444)33", borderRadius: 8,
                  padding: "8px 16px", cursor: busy === "delete" ? "default" : "pointer",
                  fontWeight: 600, fontSize: 13, width: "100%",
                  opacity: busy === "delete" ? 0.7 : 1,
                }}
              >
                {t("card.delete")}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Creation Card ──────────────────────────────────────────────────────────────

function CreationCard({ creation, onClick }: { creation: FlowCreation; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--b1)",
        borderRadius: 12,
        padding: 16,
        cursor: "pointer",
        textAlign: "start",
        display: "flex", flexDirection: "column", gap: 8,
        transition: "border-color 0.15s, box-shadow 0.15s",
        width: "100%",
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--accent)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--b1)"; }}
    >
      {creation.thumbnail_url && (
        <img
          src={creation.thumbnail_url}
          alt=""
          aria-hidden="true"
          style={{ width: "100%", borderRadius: 6, objectFit: "cover", height: 100, border: "1px solid var(--b1)" }}
        />
      )}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <TypeBadge type={creation.type} />
        <VisibilityChip visibility={creation.visibility} />
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", lineHeight: 1.3 }}>
        {creation.title}
      </div>
      {creation.description && (
        <div style={{
          fontSize: 11.5, color: "var(--t4)", lineHeight: 1.5,
          overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
        }}>
          {creation.description}
        </div>
      )}
      <div style={{ fontSize: 10, color: "var(--t5)", marginTop: "auto" }}>
        {new Date(creation.created_at).toLocaleDateString()}
      </div>
    </button>
  );
}

// ── Filter Bar ─────────────────────────────────────────────────────────────────

const FILTERS: Array<CreationType | "ALL"> = [
  "ALL", "APP", "AGENT", "WORKFLOW", "AUTOMATION", "TEMPLATE", "DEVICE_WORKFLOW",
];

function FilterBar({
  active,
  onChange,
}: {
  active: CreationType | "ALL";
  onChange: (f: CreationType | "ALL") => void;
}) {
  const { t } = useTranslation("discover");
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {FILTERS.map(f => (
        <button
          key={f}
          onClick={() => onChange(f)}
          style={{
            fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 99,
            border: `1px solid ${active === f ? "var(--accent)" : "var(--b2)"}`,
            background: active === f ? "var(--accent)18" : "transparent",
            color: active === f ? "var(--accent)" : "var(--t4)",
            cursor: "pointer",
          }}
        >
          {f === "ALL" ? t("filters.all") : t(`filters.${f}`)}
        </button>
      ))}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export function DiscoverPage() {
  const { t } = useTranslation("discover");
  const { currentOrgId } = useOrg();

  const [tab, setTab]         = useState<"feed" | "mine">("feed");
  const [filter, setFilter]   = useState<CreationType | "ALL">("ALL");
  const [items, setItems]     = useState<FlowCreation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [selected, setSelected] = useState<FlowCreation | null>(null);
  const [toast, setToast]     = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const typeArg = filter === "ALL" ? undefined : filter;
      if (tab === "feed") {
        const resp = await fetchDiscoverFeed({ type: typeArg, limit: 50 });
        setItems(resp.items);
      } else {
        if (!currentOrgId) { setItems([]); return; }
        const resp = await fetchMyCreations(currentOrgId, { type: typeArg, limit: 50 });
        setItems(resp.items);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t("error"));
    } finally {
      setLoading(false);
    }
  }, [tab, filter, currentOrgId, t]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  const handleAction = async (action: string, id: string) => {
    if (!currentOrgId) return;
    try {
      if (action === "clone") {
        await cloneCreation(id, currentOrgId);
        showToast(t("actions.cloned"));
      } else if (action === "publish") {
        const updated = await publishCreation(id, currentOrgId);
        setItems(prev => prev.map(c => c.id === id ? updated : c));
        if (selected?.id === id) setSelected(updated);
        showToast(t("actions.published"));
      } else if (action === "unpublish") {
        const updated = await unpublishCreation(id, currentOrgId);
        setItems(prev => prev.map(c => c.id === id ? updated : c));
        if (selected?.id === id) setSelected(updated);
        showToast(t("actions.unpublished"));
      } else if (action === "delete") {
        await deleteCreation(id, currentOrgId);
        setItems(prev => prev.filter(c => c.id !== id));
        setSelected(null);
        showToast(t("actions.deleted"));
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : t("actions.cloneError"));
    }
  };

  const isMineTab = tab === "mine";
  const emptyKey = items.length === 0 && !loading
    ? (filter !== "ALL" ? "filtered" : isMineTab ? "mine" : "feed")
    : null;

  return (
    <div style={{
      height: "100%", display: "flex", flexDirection: "column",
      padding: "20px 24px", gap: 20, overflow: "hidden",
    }}>
      {/* Header */}
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 800, color: "var(--t1)", margin: 0 }}>
          {t("title")}
        </h1>
        <p style={{ fontSize: 12, color: "var(--t4)", margin: "4px 0 0" }}>
          {t("subtitle")}
        </p>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--b1)", paddingBottom: 0 }}>
        {(["feed", "mine"] as const).map(t_ => (
          <button
            key={t_}
            onClick={() => setTab(t_)}
            style={{
              background: "none", border: "none", cursor: "pointer",
              padding: "8px 14px", fontSize: 13, fontWeight: 600,
              color: tab === t_ ? "var(--accent)" : "var(--t4)",
              borderBottom: tab === t_ ? "2px solid var(--accent)" : "2px solid transparent",
              marginBottom: -1,
            }}
          >
            {t(`tabs.${t_}`)}
          </button>
        ))}
      </div>

      {/* Filter bar */}
      <FilterBar active={filter} onChange={f => { setFilter(f); }} />

      {/* Content */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {loading && (
          <div style={{ display: "flex", justifyContent: "center", paddingTop: 60, color: "var(--t4)", fontSize: 13 }}>
            {t("loading")}
          </div>
        )}

        {error && !loading && (
          <div style={{
            background: "var(--bg-surface)", border: "1px solid var(--red, #ef4444)44",
            borderRadius: 8, padding: "12px 16px", color: "var(--red, #ef4444)", fontSize: 13,
          }}>
            {error}
          </div>
        )}

        {!loading && !error && emptyKey && (
          <div style={{
            textAlign: "center", paddingTop: 60,
            color: "var(--t4)", fontSize: 13, lineHeight: 1.6,
          }}>
            {t(`empty.${emptyKey}`)}
          </div>
        )}

        {!loading && !error && items.length > 0 && (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: 16,
            paddingBottom: 24,
          }}>
            {items.map(c => (
              <CreationCard key={c.id} creation={c} onClick={() => setSelected(c)} />
            ))}
          </div>
        )}
      </div>

      {/* Detail panel */}
      {selected && (
        <DetailPanel
          creation={selected}
          orgId={currentOrgId}
          onClose={() => setSelected(null)}
          onAction={handleAction}
          isMine={isMineTab && selected.organization_id === currentOrgId}
        />
      )}

      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
          background: "var(--bg-surface)", border: "1px solid var(--b2)",
          borderRadius: 8, padding: "10px 18px",
          fontSize: 12, fontWeight: 600, color: "var(--t2)",
          boxShadow: "0 4px 16px rgba(0,0,0,0.15)",
          zIndex: 999,
        }}>
          {toast}
        </div>
      )}
    </div>
  );
}
