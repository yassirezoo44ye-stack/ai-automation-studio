import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../../utils/api";
import { PlanRunsPanel } from "./PlanRunsPanel";
import { useOrg } from "../../../contexts/OrgContext";

type Node = { key: string; title: string; acceptance: string[]; depends_on: string[]; priority: "low" | "medium" | "high" };
type Draft = { title: string; goal: string; tasks: Node[] };
type Plan = Omit<Draft, "tasks"> & { id: string; project_id: string; tasks: (Node & { status: string; task_id: string | null })[]; completed: number; total: number };
type Summary = { id: string; title: string; completed: number; total: number };

type Props = { onProjectsChanged: () => void };

export function PlansTab(props: Props) {
  const { currentOrgId } = useOrg();
  return <PlansContent key={currentOrgId ?? "personal"} {...props} />;
}

function PlansContent({ onProjectsChanged }: Props) {
  const { t } = useTranslation("ai");
  const [goal, setGoal] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [plans, setPlans] = useState<Summary[]>([]);
  const [active, setActive] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingPlans, setLoadingPlans] = useState(true);
  const [error, setError] = useState("");
  const requestId = useRef("");
  const generation = useRef(0);
  const listRequest = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const context = generation.current;
    const sequence = ++listRequest.current;
    try {
      const response = await apiFetch("/api/project-plans", { signal });
      const data = await parseJSON<{ plans: Summary[] }>(response, "/api/project-plans");
      if (!signal?.aborted && context === generation.current && sequence === listRequest.current) setPlans(data.plans);
    } catch (cause) {
      if (!signal?.aborted && context === generation.current && sequence === listRequest.current) throw cause;
    } finally {
      if (!signal?.aborted && context === generation.current && sequence === listRequest.current) setLoadingPlans(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    generation.current += 1;
    void Promise.resolve().then(() => refresh(controller.signal)).catch(() => {
      if (!controller.signal.aborted) setError("plans.loadFailed");
    });
    return () => { controller.abort(); generation.current += 1; };
  }, [refresh]);

  async function action(run: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError("");
    const context = generation.current;
    try { await run(); }
    catch (cause) {
      if (context === generation.current) setError(cause instanceof Error ? cause.message : t("plans.failed"));
    } finally { if (context === generation.current) setBusy(false); }
  }

  async function generate() {
    const context = generation.current;
    await action(async () => {
      const response = await apiFetch("/api/project-plans/draft", { method: "POST", body: JSON.stringify({ goal }) });
      const data = await parseJSON<{ draft: Draft }>(response, "/api/project-plans/draft");
      if (context !== generation.current) return;
      requestId.current = crypto.randomUUID();
      setDraft(data.draft); setActive(null);
    });
  }

  async function save() {
    const context = generation.current;
    await action(async () => {
      const response = await apiFetch("/api/project-plans", { method: "POST", body: JSON.stringify({ draft, request_id: requestId.current }) });
      const plan = await parseJSON<Plan>(response, "/api/project-plans");
      if (context !== generation.current) return;
      setActive(plan); setDraft(null); onProjectsChanged();
      await refresh().catch(() => { if (context === generation.current) setError("plans.loadFailed"); });
    });
  }

  async function open(id: string) {
    const context = generation.current;
    await action(async () => {
      const response = await apiFetch(`/api/project-plans/${id}`);
      const plan = await parseJSON<Plan>(response, `/api/project-plans/${id}`);
      if (context === generation.current) { setActive(plan); setDraft(null); }
    });
  }

  async function status(key: string, value: string) {
    if (!active) return;
    const context = generation.current;
    await action(async () => {
      const path = `/api/project-plans/${active.id}/tasks/${key}`;
      const response = await apiFetch(path, { method: "PUT", body: JSON.stringify({ status: value }) });
      const plan = await parseJSON<Plan>(response, path);
      if (context === generation.current) {
        setActive(plan);
        await refresh().catch(() => { if (context === generation.current) setError("plans.loadFailed"); });
      }
    });
  }

  return <section style={{ padding: 24, overflowY: "auto" }} aria-label={t("plans.heading")}>
    <h2>{t("plans.heading")}</h2>
    <p>{t("plans.intro")}</p>
    <label htmlFor="plan-goal">{t("plans.goal")}</label>
    <textarea id="plan-goal" className="g-input" maxLength={4000} value={goal} onChange={event => setGoal(event.target.value)} disabled={busy} />
    <button className="g-btn" disabled={busy || goal.trim().length < 3} onClick={() => void generate()}>{t("plans.generate")}</button>
    {busy && <p role="status">{t("plans.working")}</p>}
    {error && <p role="alert">{error === "plans.loadFailed" ? t(error) : error}</p>}
    {draft && <article>
      <h3>{t("plans.review")}</h3>
      <label htmlFor="plan-title">{t("plans.title")}</label>
      <input id="plan-title" className="g-input" maxLength={100} value={draft.title} disabled={busy}
        onChange={event => setDraft({ ...draft, title: event.target.value })} />
      {draft.tasks.map((node, index) => <fieldset key={node.key}>
        <legend>{t("plans.task", { number: index + 1 })}</legend>
        <label htmlFor={`draft-${node.key}`}>{t("plans.taskTitle")}</label>
        <input id={`draft-${node.key}`} className="g-input" value={node.title} maxLength={300} disabled={busy}
          onChange={event => setDraft({ ...draft, tasks: draft.tasks.map(n => n.key === node.key ? { ...n, title: event.target.value } : n) })} />
        <label htmlFor={`acceptance-${node.key}`}>{t("plans.acceptance")}</label>
        <textarea id={`acceptance-${node.key}`} className="g-input" value={node.acceptance.join("\n")} disabled={busy}
          onChange={event => setDraft({ ...draft, tasks: draft.tasks.map(n => n.key === node.key ? { ...n, acceptance: event.target.value.split("\n") } : n) })} />
        {node.depends_on.length > 0 && <p>{t("plans.dependencies")}: {node.depends_on.map(key => draft.tasks.find(n => n.key === key)?.title ?? key).join(", ")}</p>}
      </fieldset>)}
      <button disabled={busy || draft.title.trim().length < 2} onClick={() => void save()}>{t("plans.save")}</button>
      <button disabled={busy} onClick={() => setDraft(null)}>{t("plans.discard")}</button>
    </article>}
    {active && <article>
      <h3>{active.title}</h3><p>{active.goal}</p>
      <p>{t("plans.progress", { completed: active.completed, total: active.total })}</p>
      <p>{t("plans.manual")}</p>
      {active.tasks.map(node => {
        const blocked = node.depends_on.some(key => active.tasks.find(n => n.key === key)?.status !== "done");
        return <fieldset key={node.key}>
          <legend>{node.title}</legend>
          <ul>{node.acceptance.map((criterion, i) => <li key={i}>{criterion}</li>)}</ul>
          {blocked && <p>{t("plans.blocked")}</p>}
          <label htmlFor={`state-${node.key}`}>{t("plans.status")}</label>
          <select id={`state-${node.key}`} value={node.status} disabled={busy || node.status === "deleted"}
            onChange={event => void status(node.key, event.target.value)}>
            {["pending", "in_progress", "done", ...(node.status === "deleted" ? ["deleted"] : [])].map(value =>
              <option key={value} value={value} disabled={blocked && value !== "pending"}>{t(`plans.states.${value}`)}</option>)}
          </select>
        </fieldset>;
      })}
      <PlanRunsPanel key={active.id} planId={active.id} tasks={active.tasks} onStarted={() => { void open(active.id); }} />
    </article>}
    <h3>{t("plans.saved")}</h3>
    {loadingPlans && <p role="status">{t("plans.working")}</p>}
    {plans.length === 0 && !busy && !loadingPlans && !error && <p>{t("plans.empty")}</p>}
    {plans.map(plan => <button key={plan.id} disabled={busy} onClick={() => void open(plan.id)} style={{ display: "block", marginBlock: 8 }}>
      {plan.title} — {plan.completed}/{plan.total}
    </button>)}
  </section>;
}
