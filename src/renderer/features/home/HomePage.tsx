/** Home contains current work only; discovery and administration live in their workspaces. */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "../../contexts/app";
import { useOrg } from "../../contexts/OrgContext";
import { useLangContext } from "../../contexts/lang";
import { apiFetch, parseJSON } from "../../utils/api";
import { relTime } from "../../utils/time";
import { useAsyncData } from "../../shared/hooks/useAsyncData";
import { handOffToAssistant } from "../../shared/utils/assistantHandoff";
import type { Project } from "../../types";
import "./home.css";

type Stats = { failed_runs?: number };
type Workflow = { id: string; name: string; status: string };
type Review = { project_id: string; idea_text: string };

export function HomePage() {
  const { loading, currentOrgId } = useOrg();
  const orgReady = !loading && !!currentOrgId;
  return <HomeContent key={orgReady ? currentOrgId : "no-org"} currentOrgId={currentOrgId} orgReady={orgReady} />;
}

function HomeContent({ currentOrgId, orgReady }: { currentOrgId: string | null; orgReady: boolean }) {
  const { setPage, setActiveProject } = useAppContext();
  const { t } = useTranslation("home");
  const { lang } = useLangContext();
  const [question, setQuestion] = useState("");
  const stats = useAsyncData<Stats>(() => apiFetch("/api/stats").then(r => parseJSON<Stats>(r, "/api/stats")), []);
  const projects = useAsyncData<Project[]>(() => apiFetch("/api/projects").then(r => parseJSON<Project[]>(r, "/api/projects")), []);
  const workflows = useAsyncData<{ runs?: Workflow[] }>(() => apiFetch("/api/workflows/active").then(r => parseJSON<{ runs?: Workflow[] }>(r, "/api/workflows/active")), [currentOrgId], { enabled: orgReady });
  const approvals = useAsyncData<{ pending?: string[] }>(() => apiFetch("/api/workflows/approvals/pending").then(r => parseJSON<{ pending?: string[] }>(r, "/api/workflows/approvals/pending")), [currentOrgId], { enabled: orgReady });
  const reviews = useAsyncData<{ pending_security_reviews?: Review[] }>(() => apiFetch("/api/saas-factory/projects/pending-review").then(r => parseJSON<{ pending_security_reviews?: Review[] }>(r, "/api/saas-factory/projects/pending-review")), [currentOrgId], { enabled: orgReady });
  const pendingCount = approvals.data?.pending?.length ?? 0;
  const reviewCount = reviews.data?.pending_security_reviews?.length ?? 0;
  const failedCount = stats.data?.failed_runs ?? 0;
  const active = (workflows.data?.runs ?? []).filter(run => run.status === "running");
  const recent = [...(projects.data ?? [])].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 5);
  const checks = [
    { key: "stats", query: stats },
    ...(orgReady ? [{ key: "approvals", query: approvals }, { key: "reviews", query: reviews }, { key: "workflows", query: workflows }] : []),
  ];
  const errors = checks.filter(check => check.query.status === "error");
  const needsAttention = failedCount > 0 || pendingCount > 0 || reviewCount > 0 || errors.length > 0;

  function ask() {
    if (!question.trim()) return;
    handOffToAssistant(question.trim());
    setPage("ai");
  }

  return <div className="home-workspace">
    <header className="home-workspace__heading">
      <h1>{t("work.title")}</h1>
      <button className="home-workspace__primary" onClick={() => setPage("new-project")}>{t("cc.newProject")}</button>
    </header>

    <section className="home-workspace__ask" aria-labelledby="home-request-title">
      <h2 id="home-request-title">{t("cc.ask.title")}</h2>
      <form onSubmit={event => { event.preventDefault(); ask(); }}>
        <label className="sr-only" htmlFor="home-question">{t("cc.ask.label")}</label>
        <textarea id="home-question" value={question} onChange={event => setQuestion(event.target.value)} placeholder={t("work.placeholder")} rows={2} />
        <button className="home-workspace__primary" type="submit" disabled={!question.trim()}>{t("cc.ask.submit")}</button>
      </form>
    </section>

    {needsAttention && <section className="home-workspace__section" aria-labelledby="home-attention-title">
      <h2 id="home-attention-title">{t("cc.attention.title")}</h2>
      {failedCount > 0 && <button className="home-workspace__row" onClick={() => setPage("runs")}>{t("cc.attention.failedRuns", { count: failedCount })}<span aria-hidden="true">←</span></button>}
      {pendingCount > 0 && <button className="home-workspace__row" onClick={() => setPage("automation")}>{t("cc.attention.approvals", { count: pendingCount })}<span aria-hidden="true">←</span></button>}
      {reviewCount > 0 && <button className="home-workspace__row" onClick={() => setPage("saas-factory")}>{t("cc.attention.security", { count: reviewCount })}<span aria-hidden="true">←</span></button>}
      {errors.map(({ key, query }) => <div className="home-workspace__error" key={key} role="alert"><span>{t(`work.errors.${key}`)}</span><button onClick={query.refetch}>{t("work.retry")}</button></div>)}
    </section>}

    <section className="home-workspace__section" aria-labelledby="home-projects-title">
      <h2 id="home-projects-title">{t("work.recentProjects")}</h2>
      {projects.status === "loading" ? <p role="status">{t("work.loading")}</p>
        : projects.status === "error" ? <div role="alert" className="home-workspace__error"><span>{t("work.errors.projects")}</span><button onClick={projects.refetch}>{t("work.retry")}</button></div>
        : recent.length === 0 ? <p>{t("work.noProjects")}</p>
        : <ul className="home-workspace__list">{recent.map(project => <li key={project.id}>
          <button className="home-workspace__row" onClick={() => setActiveProject(project.id, "build")}>
            <span>{project.name}</span><time dateTime={project.created_at}>{relTime(project.created_at, lang)}</time>
          </button>
        </li>)}</ul>}
      {(projects.data?.length ?? 0) > 5 && <button className="home-workspace__link" onClick={() => setPage("app-builder")}>{t("work.allProjects")}</button>}
    </section>

    {active.length > 0 && <section className="home-workspace__section" aria-labelledby="home-running-title">
      <h2 id="home-running-title">{t("work.running")}</h2>
      <ul className="home-workspace__list">{active.slice(0, 3).map(run => <li key={run.id}><button className="home-workspace__row" onClick={() => setPage("automation")}><span>{run.name}</span><span>{t("work.inProgress")}</span></button></li>)}</ul>
      {active.length > 3 && <button onClick={() => setPage("automation")}>{t("work.allRunning", { count: active.length })}</button>}
    </section>}
  </div>;
}
