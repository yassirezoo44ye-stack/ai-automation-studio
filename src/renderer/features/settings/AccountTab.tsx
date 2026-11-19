import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../utils/api";
import { useAuth } from "../../contexts/AuthContext";
import { GlassCard } from "../../shared/ui/gold";
import { LegalLinks } from "../legal/LegalPage";

type DeleteError = { message: string; organizations?: string[] };

async function readError(res: Response, fallback: string): Promise<DeleteError> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object") {
      return { message: String(detail.message ?? fallback), organizations: detail.organizations };
    }
    if (typeof detail === "string") return { message: detail };
  } catch { /* non-JSON body */ }
  return { message: fallback };
}

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "9px 12px", borderRadius: 8, border: "1px solid var(--b1)",
  background: "var(--bg-input, var(--bg-base))", color: "var(--t1)", fontSize: 13, boxSizing: "border-box",
};

const ghostBtn: React.CSSProperties = {
  padding: "8px 14px", borderRadius: 8, border: "1px solid var(--b2)", background: "var(--bg-input)",
  color: "var(--t2)", fontSize: 13, fontWeight: 500, cursor: "pointer",
};
const dangerBtn: React.CSSProperties = {
  padding: "8px 14px", borderRadius: 8, border: "1px solid var(--red)", background: "var(--red-dim)",
  color: "var(--red)", fontSize: 13, fontWeight: 600, cursor: "pointer",
};

/** Privacy rights in one place: download a copy of your data, delete the account. */
export function AccountTab() {
  const { t } = useTranslation("settings");
  const { user, logout } = useAuth();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<DeleteError | null>(null);

  if (!user) return null;
  const needsPassword = user.has_password !== false;
  const emailMatches = email.trim().toLowerCase() === user.email.toLowerCase();
  const canDelete = emailMatches && (!needsPassword || password.length > 0) && !deleting;

  const downloadData = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const res = await apiFetch("/api/auth/me/export");
      if (!res.ok) throw new Error((await readError(res, t("account.exportFailed"))).message);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `flow-data-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : t("account.exportFailed"));
    } finally {
      setExporting(false);
    }
  };

  const deleteAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const res = await apiFetch("/api/auth/me", {
        method: "DELETE",
        body: JSON.stringify(needsPassword ? { email: email.trim(), password } : { email: email.trim() }),
      });
      if (!res.ok) {
        setDeleteError(await readError(res, t("account.deleteFailed")));
        return;
      }
      await logout();
      window.location.assign("/");
    } catch {
      setDeleteError({ message: t("account.deleteFailed") });
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 600, animation: "slideUp .2s ease" }}>
      <div>
        <div className="section-label" style={{ marginBottom: 12 }}>{t("account.exportTitle")}</div>
        <GlassCard lift={false}>
          <p style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.7, margin: "0 0 12px" }}>{t("account.exportBody")}</p>
          <button type="button" style={ghostBtn} onClick={downloadData} disabled={exporting} data-testid="export-data">
            {exporting ? t("account.exporting") : t("account.exportButton")}
          </button>
          {exportError && <p role="alert" style={{ color: "var(--red)", fontSize: 12, margin: "10px 0 0" }}>{exportError}</p>}
        </GlassCard>
      </div>

      <div>
        <div className="section-label" style={{ marginBottom: 12 }}>{t("account.deleteTitle")}</div>
        <GlassCard lift={false} style={{ borderColor: "var(--red)" }}>
          <p style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.7, margin: "0 0 12px" }}>{t("account.deleteBody")}</p>
          {!confirming ? (
            <button type="button" style={dangerBtn} onClick={() => setConfirming(true)} data-testid="delete-account-start">
              {t("account.deleteButton")}
            </button>
          ) : (
            <form onSubmit={deleteAccount} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <label style={{ fontSize: 12, color: "var(--t3)" }}>
                {t("account.typeEmail", { email: user.email })}
                <input style={{ ...inputStyle, marginTop: 6 }} value={email} onChange={e => setEmail(e.target.value)}
                  autoComplete="off" aria-label={t("account.typeEmail", { email: user.email })} data-testid="delete-email" />
              </label>
              {needsPassword && (
                <label style={{ fontSize: 12, color: "var(--t3)" }}>
                  {t("account.password")}
                  <input type="password" style={{ ...inputStyle, marginTop: 6 }} value={password}
                    onChange={e => setPassword(e.target.value)} autoComplete="current-password" data-testid="delete-password" />
                </label>
              )}
              {deleteError && (
                <div role="alert" style={{ color: "var(--red)", fontSize: 12, lineHeight: 1.6 }}>
                  {deleteError.organizations?.length
                    ? t("account.transferFirst", { orgs: deleteError.organizations.join("، ") })
                    : deleteError.message}
                </div>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button type="submit" style={{ ...dangerBtn, opacity: canDelete ? 1 : 0.5, cursor: canDelete ? "pointer" : "not-allowed" }} disabled={!canDelete} data-testid="delete-account-confirm">
                  {deleting ? t("account.deleting") : t("account.deleteConfirm")}
                </button>
                <button type="button" style={ghostBtn} onClick={() => { setConfirming(false); setDeleteError(null); }}>
                  {t("account.cancel")}
                </button>
              </div>
            </form>
          )}
        </GlassCard>
      </div>

      <LegalLinks />
    </div>
  );
}
