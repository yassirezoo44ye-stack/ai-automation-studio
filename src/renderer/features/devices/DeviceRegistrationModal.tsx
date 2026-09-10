import { useState } from "react";
import { useTranslation } from "react-i18next";
import { devicesService } from "./services/devicesService";
import type { EnrollmentToken } from "./types/devices.types";

interface Props {
  onClose: () => void;
}

export function DeviceRegistrationModal({ onClose }: Props) {
  const { t } = useTranslation("devices");
  const [loading,  setLoading]  = useState(false);
  const [token,    setToken]    = useState<EnrollmentToken | null>(null);
  const [error,    setError]    = useState<string | null>(null);
  const [copied,   setCopied]   = useState(false);

  const generate = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await devicesService.createEnrollmentToken();
      setToken(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create enrollment token");
    } finally {
      setLoading(false);
    }
  };

  const copyToken = () => {
    if (!token) return;
    void navigator.clipboard.writeText(token.enrollment_token);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={overlayStyle} onClick={onClose} role="dialog" aria-modal="true" aria-label={t("modal.title")}>
      <div style={panelStyle} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", marginBottom: 20 }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: "var(--t1)", flex: 1 }}>
            {t("modal.title")}
          </h2>
          <button onClick={onClose} style={closeBtnStyle} aria-label="Close">✕</button>
        </div>

        {/* Instructions */}
        <p style={{ fontSize: 13, color: "var(--t3)", lineHeight: 1.6, marginBottom: 18 }}>
          {t("modal.instructions")}
        </p>

        {/* Steps */}
        {!token && (
          <ol style={{ fontSize: 13, color: "var(--t4)", paddingLeft: 20, lineHeight: 2, marginBottom: 20 }}>
            <li>{t("modal.step1")}</li>
            <li>{t("modal.step2")}</li>
            <li>{t("modal.step3")}</li>
          </ol>
        )}

        {/* Token display */}
        {token && (
          <div style={{ background: "var(--bg-input)", border: "1px solid var(--b1)", borderRadius: 10, padding: 16, marginBottom: 18 }}>
            <div style={{ fontSize: 11, color: "var(--t5)", marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {t("modal.tokenLabel")}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <code style={{ flex: 1, fontSize: 12, color: "var(--teal)", wordBreak: "break-all", fontFamily: "monospace" }}>
                {token.enrollment_token}
              </code>
              <button onClick={copyToken} style={copyBtnStyle}>
                {copied ? "✓" : t("modal.copy")}
              </button>
            </div>
            <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 8 }}>
              {t("modal.expiresAt", { date: new Date(token.expires_at).toLocaleString() })}
            </div>

            {/* Security warning */}
            <div style={{ marginTop: 12, padding: "8px 10px", background: "rgba(231, 76, 60, 0.1)", borderRadius: 7, border: "1px solid rgba(231, 76, 60, 0.2)", fontSize: 12, color: "#e74c3c" }}>
              ⚠️ {t("modal.securityWarning")}
            </div>
          </div>
        )}

        {/* Command for agent */}
        {token && (
          <div style={{ background: "var(--bg-input)", borderRadius: 8, padding: 12, marginBottom: 18, fontFamily: "monospace", fontSize: 12, color: "var(--t3)" }}>
            <div style={{ color: "var(--t5)", fontSize: 11, marginBottom: 4 }}>{t("modal.agentCommand")}</div>
            <code style={{ color: "var(--teal)" }}>
              python -m agent enroll --server YOUR_SERVER_URL --token {token.enrollment_token}
            </code>
          </div>
        )}

        {error && (
          <div style={{ padding: "8px 12px", background: "rgba(231,76,60,0.1)", borderRadius: 7, color: "#e74c3c", fontSize: 13, marginBottom: 14 }}>
            {error}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={secondaryBtnStyle}>{t("modal.close")}</button>
          {!token && (
            <button onClick={() => void generate()} disabled={loading} style={primaryBtnStyle}>
              {loading ? t("modal.generating") : t("modal.generate")}
            </button>
          )}
          {token && (
            <button onClick={() => { setToken(null); setCopied(false); }} style={secondaryBtnStyle}>
              {t("modal.generateAnother")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

const overlayStyle: React.CSSProperties = {
  position: "fixed", inset: 0, zIndex: 1000,
  background: "rgba(0,0,0,0.6)",
  display: "flex", alignItems: "center", justifyContent: "center",
};

const panelStyle: React.CSSProperties = {
  background: "var(--card, #161622)",
  border: "1px solid var(--b1)",
  borderRadius: 16,
  padding: "24px 26px",
  width: 480, maxWidth: "95vw",
  maxHeight: "90vh", overflowY: "auto",
  boxShadow: "0 24px 64px rgba(0,0,0,0.5)",
};

const closeBtnStyle: React.CSSProperties = {
  background: "none", border: "none",
  color: "var(--t5)", cursor: "pointer",
  fontSize: 18, padding: 4, lineHeight: 1,
};

const primaryBtnStyle: React.CSSProperties = {
  background: "var(--accent)", color: "#fff",
  border: "none", borderRadius: 9, cursor: "pointer",
  padding: "9px 18px", fontSize: 13, fontWeight: 600,
};

const secondaryBtnStyle: React.CSSProperties = {
  background: "var(--bg-input)", color: "var(--t3)",
  border: "1px solid var(--b1)", borderRadius: 9, cursor: "pointer",
  padding: "9px 18px", fontSize: 13,
};

const copyBtnStyle: React.CSSProperties = {
  background: "var(--bg-elevated)", color: "var(--t3)",
  border: "1px solid var(--b1)", borderRadius: 7, cursor: "pointer",
  padding: "4px 10px", fontSize: 12, flexShrink: 0,
};
