import { useTranslation } from "react-i18next";
import type { useFlowSkill } from "../hooks/useFlowSkill";

export function FlowSkillSelect({ selection }: { selection: ReturnType<typeof useFlowSkill> }) {
  const { t } = useTranslation("ai");
  return (
    <div>
      <select className="g-input" aria-label={t("skills.selectionLabel")}
        value={selection.skillId} onChange={event => selection.selectSkill(event.target.value)}>
        <option value="">{t("skills.none")}</option>
        {selection.skills.map(skill => <option key={skill.id} value={skill.id}>{skill.title}</option>)}
      </select>
      <small>{t("skills.persistenceHint")}</small>
      {selection.failed && <small role="alert">{t("skills.loadFailed")}</small>}
    </div>
  );
}
