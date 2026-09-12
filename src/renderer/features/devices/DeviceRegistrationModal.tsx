import { useState } from "react";
import { useTranslation } from "react-i18next";
import { devicesService } from "./services/devicesService";
import type { EnrollmentToken } from "./types/devices.types";

interface Props {
  onClose: () => void;
}

type Step = 1 | 2 | 3;

export function DeviceRegistrationModal({ onClose }: Props) {
  const { t } = useTranslation("devices");
  const [loading,  setLoading]  = useState(false);
  const [token,    setToken]    = useState<EnrollmentToken | null>(null);
  const [error,    setError]    = useState<string | null>(null);
  const [copied,   setCopied]   = useState(false);

  const currentStep: Step = token ? 2 : 1;

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
    setTimeout(() => setCopied(false), 2500);
  };

  const reset = () => {
    setToken(null);
    setCopied(false);
  };

  return (
    <div
      style={overlayStyle}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
      role="button"
      tabIndex={0}
      aria-label="Close modal"
    >
      <div
        style={panelStyle}
        role="dialog"
        aria-modal="true"
        aria-label={t("modal.title")}
        tabIndex={-1}
      >

        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", marginBottom: 20 }}>
          <div style={{ flex: 1 }}>
            <h2 style={{ margin: "0 0 4px", fontSize: 18, fontWeight: 700, color: "var(--t1)" }}>
              {t("modal.title")}
            </h2>
            <p style={{ margin: 0, fontSize: 12, color: "var(--t5)", lineHeight: 1.4 }}>
              {t("modal.instructions")}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={closeBtnStyle}
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        {/* Step indicator */}
        <StepIndicator current={currentStep} total={3} />

        {/* Step 1: Instructions */}
        {!token && (
          <div style={{ marginBottom: 22 }}>
            <ol style={{ margin: 0, paddingLeft: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 12 }}>
              {[
                t("modal.step1"),
                t("modal.step2"),
                t("modal.step3"),
              ].map((step, i) => (
                <li key={i} style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                  <span style={{
                    width: 24, height: 24, borderRadius: "50%",
                    background: i === 0 ? "var(--accent)" : "var(--bg-input)",
                    border: `1px solid ${i === 0 ? "var(--accent)" : "var(--b1)"}`,
                    color: i === 0 ? "#fff" : "var(--t5)",
                    fontSize: 11, fontWeight: 700,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    flexShrink: 0, marginTop: 1,
                  }}>
                    {i + 1}
                  </span>
                  <span style={{ fontSize: 13, color: i === 0 ? "var(--t2)" : "var(--t4)", lineHeight: 1.5, paddingTop: 3 }}>
                    {step}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Step 2: Token display */}
        {token && (
          <>
            <div style={{
              background: "var(--bg-input)",
              border: "1px solid var(--b1)",
              borderRadius: 12, padding: 16, marginBottom: 14,
            }}>
              <div style={{ fontSize: 11, color: "var(--t5)", marginBottom: 8, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {t("modal.tokenLabel")}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <code style={{
                  flex: 1, fontSize: 12, color: "var(--teal, #2ecc71)",
                  wordBreak: "break-all", fontFamily: "monospace",
                  background: "var(--card)", padding: "8px 10px",
                  borderRadius: 7, lineHeight: 1.5,
                }}>
                  {token.enrollment_token}
                </code>
                <button
                  type="button"
                  onClick={copyToken}
                  aria-label={copied ? t("modal.copied") : t("modal.copy")}
                  style={{
                    ...copyBtnStyle,
                    background: copied ? "rgba(46,204,113,0.15)" : "var(--bg-elevated)",
                    color: copied ? "#2ecc71" : "var(--t3)",
                    borderColor: copied ? "rgba(46,204,113,0.35)" : "var(--b1)",
                    transition: "background 0.2s, color 0.2s",
                  }}
                >
                  {copied ? "✓" : t("modal.copy")}
                </button>
              </div>
              <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 8 }}>
                {t("modal.expiresAt", { date: new Date(token.expires_at).toLocaleString() })}
              </div>
            </div>

            {/* Security warning */}
            <div style={{
              marginBottom: 14,
              padding: "10px 12px",
              background: "rgba(231,76,60,0.08)",
              border: "1px solid rgba(231,76,60,0.2)",
              borderRadius: 9, fontSize: 12, color: "#e74c3c",
              display: "flex", gap: 8, alignItems: "flex-start",
            }}>
              <span style={{ fontSize: 14, flexShrink: 0 }}>⚠️</span>
              <span>{t("modal.securityWarning")}</span>
            </div>

            {/* Agent command */}
            <div style={{
              background: "var(--bg-input)", borderRadius: 9, padding: 12,
              marginBottom: 18, fontFamily: "monospace",
            }}>
              <div style={{ fontSize: 10, color: "var(--t5)", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {t("modal.agentCommand")}
              </div>
              <code style={{ fontSize: 12, color: "var(--t3)", lineHeight: 1.6, wordBreak: "break-all" }}>
                python -m agent enroll --server YOUR_SERVER_URL --token{" "}
                <span style={{ color: "var(--teal, #2ecc71)" }}>{token.enrollment_token}</span>
              </code>
            </div>
          </>
        )}

        {error && (
          <div style={{
            padding: "8px 12px", background: "rgba(231,76,60,0.1)",
            borderRadius: 7, color: "#e74c3c", fontSize: 13, marginBottom: 14,
          }}>
            {error}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose} style={secondaryBtnStyle}>
            {t("modal.close")}
          </button>
          {!token && (
            <button
              type="button"
              onClick={() => void generate()}
              disabled={loading}
              style={{ ...primaryBtnStyle, opacity: loading ? 0.65 : 1, cursor: loading ? "wait" : "pointer" }}
            >
              {loading ? t("modal.generating") : t("modal.generate")}
            </button>
          )}
          {token && (
            <button type="button" onClick={reset} style={secondaryBtnStyle}>
              {t("modal.generateAnother")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Step indicator ────────────────────────────────────────────────────────────

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 0, marginBottom: 22 }}>
      {Array.from({ length: total }, (_, i) => {
        const step = i + 1;
        const done   = step < current;
        const active = step === current;
        return (
          <div key={step} style={{ display: "flex", alignItems: "center", flex: step < total ? 1 : "none" }}>
            <div style={{
              width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 12, fontWeight: 700,
              background: done ? "var(--accent)" : active ? "rgba(var(--accent-rgb,120,80,220),0.15)" : "var(--bg-input)",
              border: `2px solid ${done ? "var(--accent)" : active ? "var(--accent)" : "var(--b1)"}`,
              color: done ? "#fff" : active ? "var(--accent)" : "var(--t5)",
              transition: "all 0.2s",
            }}>
              {done ? (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              ) : step}
            </div>
            {step < total && (
              <div style={{
                flex: 1, height: 2, margin: "0 4px",
                background: done ? "var(--accent)" : "var(--b1)",
                transition: "background 0.3s",
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const overlayStyle: React.CSSProperties = {
  position: "fixed", inset: 0, zIndex: 1000,
  background: "rgba(0,0,0,0.65)",
  display: "flex", alignItems: "center", justifyContent: "center",
  backdropFilter: "blur(3px)",
};

const panelStyle: React.CSSProperties = {
  background: "var(--card, #161622)",
  border: "1px solid var(--b1)",
  borderRadius: 18,
  padding: "26px 28px",
  width: 500, maxWidth: "95vw",
  maxHeight: "92vh", overflowY: "auto",
  boxShadow: "0 32px 80px rgba(0,0,0,0.5)",
};

const closeBtnStyle: React.CSSProperties = {
  background: "none", border: "none",
  color: "var(--t5)", cursor: "pointer",
  padding: 6, borderRadius: 7, lineHeight: 1,
  display: "flex", alignItems: "center",
  flexShrink: 0, marginLeft: 12,
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
  padding: "6px 12px", fontSize: 12, flexShrink: 0, fontWeight: 600,
};
