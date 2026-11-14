import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { PhaseCard } from "./PhaseCard";
import type { FactoryPhase, FactoryProject, SecurityFinding, SecurityReviewCheckpoint } from "../types/saasFactory.types";

const PHASE_ORDER: FactoryPhase[] = [
  "IDEA", "BLUEPRINT", "BUILDING", "TESTING",
  "VERIFYING", "DEPLOYING", "LIVE",
];

function phaseStatus(
  phase: FactoryPhase,
  currentPhase: FactoryPhase,
  checkpoint: Record<string, unknown>,
): "pending" | "active" | "done" | "failed" {
  if (currentPhase === "FAILED") {
    if (phase in checkpoint) return "done";
    const failedPhase = PHASE_ORDER.find(p => !(p in checkpoint));
    if (phase === failedPhase) return "failed";
    return "pending";
  }
  // PENDING_REVIEW sits between VERIFYING and DEPLOYING — phases up to VERIFYING are done.
  if (currentPhase === "PENDING_REVIEW") {
    const verifyingIdx = PHASE_ORDER.indexOf("VERIFYING");
    return PHASE_ORDER.indexOf(phase) <= verifyingIdx ? "done" : "pending";
  }
  const phaseIdx   = PHASE_ORDER.indexOf(phase);
  const currentIdx = PHASE_ORDER.indexOf(currentPhase);
  if (phaseIdx < currentIdx) return "done";
  if (phaseIdx === currentIdx) return currentPhase === "LIVE" ? "done" : "active";
  return "pending";
}

const SEVERITY_COLOR: Record<string, string> = {
  info:     "#6b7280",
  warn:     "#d97706",
  critical: "#ef4444",
};
const SEVERITY_ICON: Record<string, string> = {
  info:     "ℹ",
  warn:     "⚠",
  critical: "✕",
};

interface SecurityReviewPanelProps {
  project: FactoryProject;
  onApprove: () => Promise<void>;
  onReject: (reason: string) => Promise<void>;
}

function SecurityReviewPanel({ project, onApprove, onReject }: SecurityReviewPanelProps) {
  const { t } = useTranslation("saas-factory");
  const [rejectMode, setRejectMode] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  const verifying = (project.checkpoint["VERIFYING"] ?? {}) as Partial<SecurityReviewCheckpoint>;
  const findings: SecurityFinding[] = verifying.findings ?? [];
  const rlsCovered: boolean = verifying.rls_covered ?? false;
  const waitingSince = new Date(project.updated_at).toLocaleDateString();

  const handleApprove = useCallback(async () => {
    setActionLoading(true);
    try { await onApprove(); } finally { setActionLoading(false); }
  }, [onApprove]);

  const handleReject = useCallback(async () => {
    setActionLoading(true);
    try {
      await onReject(rejectReason.trim());
      setRejectMode(false);
      setRejectReason("");
    } finally {
      setActionLoading(false);
    }
  }, [onReject, rejectReason]);

  return (
    <div className="sf-security-panel" role="region" aria-label={t("review.title")}>
      <div className="sf-security-panel__header">
        <span className="sf-security-panel__title-icon" aria-hidden="true">⚠</span>
        <div>
          <p className="sf-security-panel__title">{t("review.title")}</p>
          <p className="sf-security-panel__subtitle">{t("review.subtitle")}</p>
          <p className="sf-security-panel__waiting">
            {t("review.waitingSince")}: <strong>{waitingSince}</strong>
          </p>
        </div>
      </div>

      {findings.length > 0 && (
        <div className="sf-security-panel__findings">
          <p className="sf-security-panel__findings-label">{t("review.findings")}</p>
          {findings.map((f, i) => (
            <div key={i} className={`sf-security-finding sf-security-finding--${f.severity}`}>
              <span className="sf-security-finding__icon" style={{ color: SEVERITY_COLOR[f.severity] }}>
                {SEVERITY_ICON[f.severity]}
              </span>
              <span className="sf-security-finding__area">{f.area}:</span>
              <span className="sf-security-finding__note">{f.note}</span>
            </div>
          ))}
        </div>
      )}

      <p className={`sf-security-panel__rls ${rlsCovered ? "sf-security-panel__rls--ok" : "sf-security-panel__rls--missing"}`}>
        {rlsCovered ? `✓ ${t("review.rlsCovered")}` : `✕ ${t("review.rlsNotCovered")}`}
      </p>

      {!rejectMode ? (
        <div className="sf-security-panel__actions">
          <button
            className="sf-btn sf-btn--approve"
            onClick={handleApprove}
            disabled={actionLoading}
          >
            {actionLoading ? t("review.approving") : t("review.approve")}
          </button>
          <button
            className="sf-btn sf-btn--ghost"
            onClick={() => setRejectMode(true)}
            disabled={actionLoading}
          >
            {t("review.reject")}
          </button>
        </div>
      ) : (
        <div className="sf-security-panel__reject-area">
          <label className="sf-security-panel__reason-label" htmlFor="sf-reject-reason">
            {t("review.rejectReason")}
          </label>
          <textarea
            id="sf-reject-reason"
            className="sf-security-panel__reason-textarea"
            rows={3}
            placeholder={t("review.rejectReasonPlaceholder")}
            value={rejectReason}
            onChange={e => setRejectReason(e.target.value)}
            disabled={actionLoading}
          />
          <div className="sf-security-panel__actions">
            <button
              className="sf-btn sf-btn--danger"
              onClick={handleReject}
              disabled={actionLoading}
            >
              {actionLoading ? t("review.rejecting") : t("review.confirmReject")}
            </button>
            <button
              className="sf-btn sf-btn--ghost"
              onClick={() => { setRejectMode(false); setRejectReason(""); }}
              disabled={actionLoading}
            >
              {t("review.cancel")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

interface Props {
  project: FactoryProject;
  onResume: () => void;
  onDelete: () => void;
  onApprove: () => Promise<void>;
  onReject: (reason: string) => Promise<void>;
}

export function PipelineView({ project, onResume, onDelete, onApprove, onReject }: Props) {
  const { t } = useTranslation("saas-factory");

  const phases = PHASE_ORDER.map(phase => {
    const status = phaseStatus(phase, project.phase, project.checkpoint);
    const output = project.checkpoint[phase] as Record<string, unknown> | undefined;
    return { phase, status, output };
  });

  const isLive          = project.phase === "LIVE";
  const isFailed        = project.phase === "FAILED";
  const isPendingReview = project.phase === "PENDING_REVIEW";

  return (
    <div className="sf-pipeline">
      <div className="sf-pipeline__idea">
        <span className="sf-pipeline__idea-label">{t("pipeline.idea")}</span>
        <p className="sf-pipeline__idea-text">{project.idea_text}</p>
      </div>

      <div className="sf-pipeline__phases">
        {phases.map(({ phase, status, output }) => (
          <PhaseCard
            key={phase}
            phase={phase}
            label={t(`phases.${phase}.label`)}
            description={t(`phases.${phase}.description`)}
            status={status}
            output={output}
          />
        ))}
      </div>

      {isPendingReview && (
        <SecurityReviewPanel
          project={project}
          onApprove={onApprove}
          onReject={onReject}
        />
      )}

      {isFailed && (
        <div className="sf-pipeline__error">
          <p className="sf-pipeline__error-msg">
            {t("pipeline.failedAt")} — {project.error_message}
          </p>
          <button className="sf-btn sf-btn--primary" onClick={onResume}>
            {t("pipeline.resume")}
          </button>
        </div>
      )}

      {isLive && (
        <div className="sf-pipeline__live">
          <span className="sf-pipeline__live-badge">✦ {t("pipeline.live")}</span>
          {project.app_builder_app_id && (
            <p className="sf-pipeline__live-sub">
              {t("pipeline.appId")}: {project.app_builder_app_id}
            </p>
          )}
        </div>
      )}

      <button className="sf-btn sf-btn--ghost sf-btn--small" onClick={onDelete}>
        {t("pipeline.delete")}
      </button>
    </div>
  );
}
