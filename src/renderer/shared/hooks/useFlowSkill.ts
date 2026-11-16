import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

type Skill = { id: string; title: string };
const KEY = "flow.skill-selection.v1";

function readSelection(): string {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) ?? '""');
    return typeof value === "string" ? value : "";
  } catch { return ""; }
}

/** Only a preference is stored; tool authority always comes from the server. */
export function useFlowSkill() {
  const [savedId, setSavedId] = useState(readSelection);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void apiFetch("/api/agents/skills", { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Could not load skills");
        const body = await response.json() as { skills: Skill[] };
        if (!controller.signal.aborted) setSkills(body.skills);
      })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    const sync = (event: StorageEvent) => {
      if (event.key === KEY || event.key === null) setSavedId(readSelection());
    };
    window.addEventListener("storage", sync);
    return () => { controller.abort(); window.removeEventListener("storage", sync); };
  }, []);
  const skillId = skills.some(skill => skill.id === savedId) ? savedId : "";
  function selectSkill(value: string) {
    setSavedId(value);
    try { localStorage.setItem(KEY, JSON.stringify(value)); } catch { /* Session still works. */ }
  }
  return { skillId, selectSkill, skills, failed };
}
