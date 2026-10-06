import { useTranslation } from "react-i18next";
import { PhaseCard } from "./PhaseCard";
import type { FactoryPhase, FactoryProject } from "../types/saasFactory.types";

const PHASE_ORDER: FactoryPhase[] = [
  "IDEA", "BLUEPRINT", "BUILDING", "TESTING",
  "VERIFYING", "DEPLOYING", "LIVE",
];

function phaseStatus(
  phase: FactoryPhase,
  currentPhase: FactoryPhase,
): "pending" | "active" | "done" | "failed" {
  if (currentPhase === "FAILED") {
    const currentIdx = PHASE_ORDER.indexOf(phase);
    const failedIdx  = PHASE_ORDER.indexOf(currentPhase);
    if (currentIdx < failedIdx) return "done";
    if (currentIdx === failedIdx) return "failed";
    return "pending";
  }
  const phaseIdx   = PHASE_ORDER.indexOf(phase);
  const currentIdx = PHASE_ORDER.indexOf(currentPhase);
  if (phaseIdx < currentIdx) return "done";
  if (phaseIdx === currentIdx) return currentPhase === "LIVE" ? "done" : "active";
  return "pending";
}

interface Props {
  project: FactoryProject;
  onResume: () => void;
  onDelete: () => void;
}

export function PipelineView({ project, onResume, onDelete }: Props) {
  const { t } = useTranslation("saas-factory");

  const phases = PHASE_ORDER.map(phase => {
    const status = phaseStatus(phase, project.phase);
    const output = project.checkpoint[phase] as Record<string, unknown> | undefined;
    return { phase, status, output };
  });

  const isLive   = project.phase === "LIVE";
  const isFailed = project.phase === "FAILED";

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
