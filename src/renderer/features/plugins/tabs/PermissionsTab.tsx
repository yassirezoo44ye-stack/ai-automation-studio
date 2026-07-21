/**
 * PermissionsTab — the plugin's declared capabilities (from its manifest,
 * already embedded on the installation row — no separate fetch needed) and
 * an Approve action when a sensitive capability is awaiting admin sign-off.
 */
import { useState } from "react";
import { apiFetch } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/toast";
import { GoldButton } from "../../../shared/ui/gold";

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
          border: "1px solid rgba(245,158,11,.3)", background: "var(--yellow-dim)",
          borderRadius: 10, padding: "10px 14px",
        }}>
          <span style={{ fontSize: 12, color: "var(--yellow)" }}>
            This plugin declares sensitive capabilities and is disabled until approved.
          </span>
          <GoldButton onClick={() => void approve()} disabled={approving} style={{ padding: "5px 14px" }}>
            {approving ? "…" : "Approve"}
          </GoldButton>
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {permissions.map(p => (
          <span key={p} className={`badge badge-${SENSITIVE.has(p) ? "yellow" : "blue"}`}>
            {p}
          </span>
        ))}
      </div>
    </div>
  );
}
