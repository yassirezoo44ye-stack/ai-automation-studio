/**
 * PermissionsTab — the plugin's declared capabilities (from its manifest,
 * already embedded on the installation row — no separate fetch needed) and
 * an Approve action when a sensitive capability is awaiting admin sign-off.
 */
import { useState } from "react";
import { apiFetch } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/ToastContext";

const SENSITIVE = new Set(["network", "filesystem", "shell_exec", "credentials_read", "third_party_api"]);

export function PermissionsTab({ installationId, permissions, approved, onApproved }: {
  installationId: string;
  permissions: string[];
  approved: boolean;
  onApproved: () => void;
}) {
  const toast = useToast();
  const [approving, setApproving] = useState(false);
  const hasSensitive = permissions.some(p => SENSITIVE.has(p));

  const approve = async () => {
    setApproving(true);
    try {
      const r = await apiFetch(`/plugins/installed/${installationId}/approve`, { method: "POST" });
      if (!r.ok) throw new Error();
      toast("Plugin approved", "ok");
      onApproved();
    } catch {
      toast("Approval failed", "err");
    } finally {
      setApproving(false);
    }
  };

  if (permissions.length === 0) {
    return <div style={{ fontSize: 12, color: "var(--t4)" }}>This plugin declares no special permissions.</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {hasSensitive && !approved && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          border: "1px solid rgba(255,179,0,.3)", background: "rgba(255,179,0,.08)",
          borderRadius: 10, padding: "10px 14px",
        }}>
          <span style={{ fontSize: 12, color: "#FFB300" }}>
            This plugin declares sensitive capabilities and is disabled until approved.
          </span>
          <button
            onClick={() => void approve()}
            disabled={approving}
            style={{
              padding: "5px 14px", borderRadius: 6, border: "none", cursor: "pointer",
              background: "#FFB300", color: "#000", fontSize: 12, fontWeight: 700,
            }}
          >
            {approving ? "…" : "Approve"}
          </button>
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {permissions.map(p => (
          <span key={p} style={{
            fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 99,
            background: SENSITIVE.has(p) ? "rgba(255,179,0,.12)" : "rgba(232,200,125,.12)",
            color: SENSITIVE.has(p) ? "#FFB300" : "#E8C87D",
            border: `1px solid ${SENSITIVE.has(p) ? "rgba(255,179,0,.3)" : "rgba(232,200,125,.3)"}`,
          }}>
            {p}
          </span>
        ))}
      </div>
    </div>
  );
}
