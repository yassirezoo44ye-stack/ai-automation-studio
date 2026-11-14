import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../../utils/api";
import { useFlowSkill } from "../../../shared/hooks/useFlowSkill";

type Task = { key: string; title: string; status: string; depends_on: string[] };
type Run = { id: string; node_id: string; runner: string; skill_id: string | null; status: string; created_at: string; started_at: string | null; finished_at: string | null };
type Detail = Run & { output: string | null; error: string | null; log: string[]; acceptance_verified: false };
const active = (run: Run) => run.status === "queued" || run.status === "running";

export function PlanRunsPanel({ planId, tasks, onStarted }: { planId: string; tasks: Task[]; onStarted: () => void }) {
  const { t, i18n } = useTranslation("ai");
  const skill = useFlowSkill();
  const [taskKey, setTaskKey] = useState(tasks[0]?.key ?? "");
  const [runner, setRunner] = useState("skill");
  const [approvedFor, setApprovedFor] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const nonce = useRef<{ key: string; id: string } | null>(null);
  const alive = useRef(true);
  const base = `/api/project-plans/${planId}`;
  const configKey = JSON.stringify([planId, taskKey, runner, runner === "skill" ? skill.skillId : null]);
  const approved = approvedFor === configKey;
  const node = tasks.find(task => task.key === taskKey);
  const blocked = node?.depends_on.some(key => tasks.find(task => task.key === key)?.status !== "done");
  const hasRun = runs.some(run => run.node_id === taskKey && active(run));

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const requests = [apiFetch(base + "/runs", { signal: controller.signal })];
        if (selected) requests.push(apiFetch(base + "/runs/" + selected, { signal: controller.signal }));
        const responses = await Promise.all(requests);
        const data = await parseJSON<{ runs: Run[] }>(responses[0], base + "/runs");
        const selectedRun = selected ? await parseJSON<Detail>(responses[1], base + "/runs/" + selected) : null;
        if (controller.signal.aborted) return;
        setRuns(data.runs); setDetail(selectedRun);
        if (data.runs.some(active)) timer = setTimeout(() => { void poll(); }, 2000);
      } catch {
        if (!controller.signal.aborted) setError(t("runs.loadFailed"));
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [base, revision, selected, t]);

  async function start() {
    if (!node || busy || !approved) return;
    setBusy(true); setError("");
    const key = JSON.stringify([taskKey, runner, runner === "skill" ? skill.skillId : null]);
    if (nonce.current?.key !== key) nonce.current = { key, id: crypto.randomUUID() };
    try {
      const path = `${base}/tasks/${taskKey}/runs`;
      const response = await apiFetch(path, { method: "POST", body: JSON.stringify({
        request_id: nonce.current.id, approved, runner, skill_id: runner === "skill" ? skill.skillId : null,
      }) });
      const run = await parseJSON<Run>(response, path);
      if (!alive.current) return;
      setSelected(run.id); setApprovedFor(""); nonce.current = null;
      setRevision(value => value + 1); onStarted();
    } catch (cause) {
      if (alive.current) setError(cause instanceof Error ? cause.message : t("plans.failed"));
    } finally { if (alive.current) setBusy(false); }
  }

  async function cancel(run: Run) {
    setBusy(true); setError("");
    try {
      const path = `${base}/runs/${run.id}`;
      const response = await apiFetch(path, { method: "DELETE" });
      await parseJSON<Detail>(response, path);
      if (alive.current) { setRevision(value => value + 1); onStarted(); }
    } catch (cause) {
      if (alive.current) setError(cause instanceof Error ? cause.message : t("plans.failed"));
    } finally { if (alive.current) setBusy(false); }
  }

  async function download() {
    if (!detail) return;
    setBusy(true); setError("");
    try {
      const response = await apiFetch(`${base}/runs/${detail.id}/artifact`);
      if (!response.ok) throw new Error(t("runs.downloadFailed"));
      const blob = await response.blob();
      if (!alive.current) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `flow-run-${detail.id}.txt`; link.click();
      URL.revokeObjectURL(url);
    } catch { if (alive.current) setError(t("runs.downloadFailed")); }
    finally { if (alive.current) setBusy(false); }
  }

  return <section aria-label={t("runs.title")}>
    <h3>{t("runs.title")}</h3>
    <p>{t("runs.scope")}</p>
    <label htmlFor="run-task">{t("runs.task")}</label>
    <select id="run-task" value={taskKey} disabled={busy} onChange={event => { setTaskKey(event.target.value); setApprovedFor(""); }}>
      {tasks.map(task => <option key={task.key} value={task.key}>{task.title}</option>)}
    </select>
    <label htmlFor="run-runner">{t("runs.runner")}</label>
    <select id="run-runner" value={runner} disabled={busy} onChange={event => { setRunner(event.target.value); setApprovedFor(""); }}>
      <option value="skill">{t("runs.skill")}</option><option value="inspect_project">{t("runs.inspect")}</option>
    </select>
    {runner === "skill" && skill.failed && <p role="alert">{t("skills.loadFailed")}</p>}
    {runner === "skill" && <>
      <label htmlFor="run-skill">{t("runs.skillLabel")}</label>
      <select id="run-skill" value={skill.skillId} disabled={busy} onChange={event => { skill.selectSkill(event.target.value); setApprovedFor(""); }}>
        <option value="">{t("runs.chooseSkill")}</option>
        {skill.skills.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
    </>}
    <label style={{ display: "block" }}>
      <input type="checkbox" checked={approved} disabled={busy} onChange={event => setApprovedFor(event.target.checked ? configKey : "")} /> {t("runs.approve")}
    </label>
    <button disabled={busy || !approved || !node || node.status === "done" || node.status === "deleted" || blocked || hasRun || (runner === "skill" && !skill.skillId)} onClick={() => void start()}>{t("runs.start")}</button>
    {(blocked || hasRun) && <p>{t(blocked ? "plans.blocked" : "runs.activeTask")}</p>}
    {error && <p role="alert">{error}</p>}
    <h4>{t("runs.history")}</h4>
    {runs.map(run => <div key={run.id}>
      <button disabled={busy} onClick={() => { setSelected(run.id); setDetail(null); setRevision(value => value + 1); }}>
        {tasks.find(task => task.key === run.node_id)?.title ?? run.node_id} — {t(`runs.states.${run.status}`)}
      </button>
      <time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString(i18n.language)}</time>
      {active(run) && <button disabled={busy} onClick={() => void cancel(run)}>{t("runs.cancel")}</button>}
    </div>)}
    {detail && <article aria-label={t("runs.result")}>
      <h4>{tasks.find(task => task.key === detail.node_id)?.title ?? detail.node_id}</h4>
      <p>{t(detail.runner === "skill" ? "runs.skill" : "runs.inspect")}</p>
      <p role="status">{t(`runs.states.${detail.status}`)}</p>
      <ul>{detail.log.map((line, index) => <li key={index}>{t(`runs.events.${line}`, { defaultValue: line })}</li>)}</ul>
      {detail.error && <p role="alert">{detail.error}</p>}
      {detail.output !== null && <><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{detail.output}</pre>
        <button disabled={busy} onClick={() => void download()}>{t("runs.download")}</button></>}
      <p>{t("runs.review")}</p>
    </article>}
  </section>;
}
