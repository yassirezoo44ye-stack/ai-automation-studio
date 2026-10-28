import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useOrg } from "../../contexts/OrgContext";
import { apiFetch, parseJSON } from "../../shared/utils/api";
import "./careers.css";

type Profile = {
  summary: string; roles: string[]; sectors: string[]; skills: string[]; languages: string[]; cities: string[];
  experience_years: number | null; minimum_monthly_aed: number | null; uae_driving_license: boolean | null;
};
type Connection = {
  configured: boolean; connected: boolean; enabled: boolean; interval_hours: number; last_sync: string | null; last_error: string | null;
  missing?: string[]; redirect_uri?: string | null; lookback_days?: number; sources?: string[];
};
type Job = {
  id: string; title: string; company: string; location: string; url: string; status: string;
  description: string; source_received_at?: string | null; verification: string; deadline: string | null; source: string;
  salary: { text: string | null; kind: string; period: string; min: number | null; max: number | null };
  assessment: { score: number; expired: boolean; strengths: { kind: string; evidence: string[] }[]; gaps: string[]; checks: string[]; next_step: string };
};
const emptyProfile: Profile = { summary: "", roles: [], sectors: [], skills: [], languages: [], cities: [], experience_years: null, minimum_monthly_aed: null, uae_driving_license: null };
const states = ["new", "saved", "applied", "interview", "rejected"];

export function CareersPage() {
  const { currentOrgId } = useOrg();
  const { t } = useTranslation("careers");
  if (!currentOrgId) return <div className="career-workspace"><p>{t("chooseOrg")}</p></div>;
  return <CareerWorkspace key={currentOrgId} orgId={currentOrgId} />;
}

function CareerWorkspace({ orgId }: { orgId: string }) {
  const { t, i18n } = useTranslation("careers");
  const [profile, setProfile] = useState<Profile>(emptyProfile);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [text, setText] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("match");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [draft, setDraft] = useState("");
  const exchangeStarted = useRef(false);
  // Google returns to this exact page; the server's redirect URI must match it.
  const callbackUri = window.location.origin + "/careers";
  const request = useCallback(async <T,>(path: string, method = "GET", body?: unknown, signal?: AbortSignal) => {
    const response = await apiFetch(`/api/careers${path}`, {
      method, headers: { "X-Organization-Id": orgId },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal,
    });
    return parseJSON<T>(response, path);
  }, [orgId]);
  const load = useCallback(async (signal?: AbortSignal) => {
    const [p, j, c] = await Promise.all([
      request<Profile>("/profile", "GET", undefined, signal),
      request<{ items: Job[] }>("/jobs", "GET", undefined, signal),
      request<Connection>("/gmail", "GET", undefined, signal),
    ]);
    setProfile(p); setJobs(j.items); setConnection(c);
  }, [request]);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => load(controller.signal)).catch(e => {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Load failed");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [load]);

  async function act(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try { await work(); }
    catch (e) { setError(e instanceof Error ? e.message : t("failed")); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    if (!query.has("state") || exchangeStarted.current) return;
    const expected = sessionStorage.getItem("flow-career-oauth-org");
    // Do not consume another workspace's one-time callback.
    if (expected !== orgId) return;
    exchangeStarted.current = true;
    const code = query.get("code"), state = query.get("state");
    window.history.replaceState(null, "", "/careers");
    sessionStorage.removeItem("flow-career-oauth-org");
    void Promise.resolve().then(async () => {
      if (query.has("error") || !code) throw new Error(t("consentDenied"));
      setBusy(true);
      await request("/gmail/exchange", "POST", { code, state });
    })
      .then(() => load()).then(() => setNotice(t("connected")))
      .catch(e => setError(e instanceof Error ? e.message : t("failed")))
      .finally(() => setBusy(false));
  }, [orgId, request, load, t]);

  const visible = jobs.filter(j => filter === "all" || (filter === "expired" ? j.assessment.expired : j.status === filter));
  if (sort === "salary") visible.sort((a, b) => {
    // Only actual comparable monthly ranges are ranked; OTE/estimates are excluded.
    const amount = (j: Job) => j.salary.period === "monthly" && j.salary.kind === "listed_unverified"
      ? (j.salary.min ?? 0) : 0;
    return Number(a.assessment.expired) - Number(b.assessment.expired) || amount(b) - amount(a);
  });
  const bilingual = (s: string) => {
    const split = s.split(" / ");
    return split.length === 2 ? split[i18n.language.startsWith("ar") ? 1 : 0] : s;
  };
  function listField(key: "roles" | "skills" | "sectors" | "languages" | "cities") {
    return <label>{t(key)}<input value={profile[key].join(", ")} onChange={e => setProfile({ ...profile, [key]: e.target.value.split(/[,،]/).map(s => s.trimStart()) })} /></label>;
  }
  return <section className="career-workspace" aria-busy={busy || loading} dir={i18n.dir()}>
    <header className="career-heading">
      <div><span className="career-eyebrow">FLOW · CAREERS</span><h1>{t("title")}</h1><p>{t("subtitle")}</p></div>
      <span className="career-count">{t("jobCount", { count: jobs.length })}</span>
    </header>
    {error && <div className="career-alert career-error" role="alert">{error}<button onClick={() => void act(load)} disabled={busy}>{t("retry")}</button></div>}
    {notice && <div className="career-alert" role="status">{notice}</div>}
    {loading ? <p role="status">{t("loading")}</p> : <>
      <div className="career-setup">
        <details className="career-panel" open={!profile.summary}>
          <summary>{t("profile")}</summary>
          <form onSubmit={e => { e.preventDefault(); void act(async () => {
            await request("/profile", "PUT", { ...profile, ...Object.fromEntries(["roles", "skills", "sectors", "languages", "cities"].map(k => [k, profile[k as "roles"].map(s => s.trim()).filter(Boolean)])) });
            await load(); setNotice(t("saved"));
          }); }}>
            <label>{t("summary")}<textarea maxLength={6000} value={profile.summary} onChange={e => setProfile({ ...profile, summary: e.target.value })} /></label>
            <p className="career-muted">{t("keywordsHint")}</p>
            <div className="career-fields">{listField("roles")}{listField("sectors")}{listField("skills")}{listField("languages")}{listField("cities")}
              <label>{t("years")}<input type="number" min="0" max="60" step="0.5" value={profile.experience_years ?? ""} onChange={e => setProfile({ ...profile, experience_years: e.target.value === "" ? null : Number(e.target.value) })} /></label>
              <label>{t("minimumSalary")}<input type="number" min="0" max="1000000" value={profile.minimum_monthly_aed ?? ""} onChange={e => setProfile({ ...profile, minimum_monthly_aed: e.target.value === "" ? null : Number(e.target.value) })} /></label>
              <label>{t("license")}<select value={profile.uae_driving_license === null ? "unknown" : String(profile.uae_driving_license)} onChange={e => setProfile({ ...profile, uae_driving_license: e.target.value === "unknown" ? null : e.target.value === "true" })}>
                <option value="unknown">{t("unknown")}</option><option value="true">{t("yes")}</option><option value="false">{t("no")}</option>
              </select></label>
            </div>
            <button className="career-primary" disabled={busy}>{t("saveProfile")}</button>
          </form>
        </details>
        <div className="career-panel">
          <h2>{t("inbox")}</h2>
          <p>{t("gmailDescription", { sources: (connection?.sources ?? ["LinkedIn", "Indeed"]).join(", "), days: connection?.lookback_days ?? 14 })}</p>
          {connection && !connection.configured && <div className="career-muted" role="status">
            <p>{t("gmailNotConfigured")}</p>
            {!!connection.missing?.length && <p>{t("missingSettings")} <code>{connection.missing.join(", ")}</code></p>}
            <p>{t("registerRedirect")} <code>{callbackUri}</code></p>
          </div>}
          {connection?.configured && connection.redirect_uri && connection.redirect_uri !== callbackUri &&
            <p role="alert">{t("redirectMismatch", { configured: connection.redirect_uri, expected: callbackUri })}</p>}
          {connection?.last_error && <p role="alert">{connection.last_error}</p>}
          <div className="career-actions">
            <button disabled={busy || !connection?.configured} onClick={() => void act(async () => {
              const result = await request<{ url: string }>("/gmail/connect", "POST");
              sessionStorage.setItem("flow-career-oauth-org", orgId);
              window.location.assign(result.url);
            })}>{t(connection?.connected ? "reconnect" : "connect")}</button>
            {connection?.connected && <>
              <button disabled={busy} onClick={() => void act(async () => {
                const result = await request<{ inserted: number; busy: boolean; unparsed_messages: number }>("/gmail/sync", "POST");
                await load(); setNotice(result.busy ? t("syncBusy") : t("imported", { count: result.inserted }) + (result.unparsed_messages ? " " + t("unparsed", { count: result.unparsed_messages }) : ""));
              })}>{t("sync")}</button>
              <button disabled={busy} onClick={() => void act(async () => { await request("/gmail", "DELETE"); await load(); })}>{t("disconnect")}</button>
            </>}
          </div>
          {connection?.connected && <>
            <label className="career-checkbox"><input type="checkbox" checked={connection.enabled} disabled={busy} onChange={e => {
              const enabled = e.target.checked;
              void act(async () => { await request("/gmail/schedule", "PUT", { enabled, interval_hours: 24 }); await load(); });
            }} />{t("dailySync")}</label>
            {connection.last_sync && <p className="career-muted">{t("lastSync")}: {new Date(connection.last_sync).toLocaleString(i18n.language)}</p>}
          </>}
          <hr /><h2>{t("pasteTitle")}</h2>
          <form onSubmit={e => { e.preventDefault(); void act(async () => {
            const result = await request<{ inserted: number; warning: string | null }>("/import", "POST", { text, source: "manual" });
            await load(); setNotice(result.warning ?? t("imported", { count: result.inserted }));
          }); }}>
            <label>{t("pasteLabel")}<textarea maxLength={200000} required value={text} onChange={e => setText(e.target.value)} placeholder={t("pasteHint")} /></label>
            <button disabled={busy || !text.trim()}>{t("import")}</button>
          </form>
        </div>
      </div>
      <div className="career-toolbar"><h2>{t("opportunities")}</h2>
        <label>{t("filter")}<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">{t("all")}</option>{[...states, "expired"].map(s => <option key={s} value={s}>{t(`status.${s}`)}</option>)}</select></label>
        <label>{t("sort")}<select value={sort} onChange={e => setSort(e.target.value)}><option value="match">{t("match")}</option><option value="salary">{t("salarySort")}</option></select></label>
      </div>
      <p className="career-muted">{t("rankingNote")}</p>
      {jobs.length >= 500 && <p role="status">{t("limitNote")}</p>}
      {!visible.length && <div className="career-panel career-empty">{t("empty")}</div>}
      <div className="career-jobs">{visible.map(job => <article className="career-panel career-job" key={job.id}>
        <div className="career-job-title"><div><h3>{job.title}</h3><p>{job.company || t("unknownCompany")} · {job.location || t("unknown")}</p></div><strong className="career-score">{job.assessment.score}<small>/100</small></strong></div>
        <div className="career-tags"><span>{job.source}</span><span>{t(`verification.${job.verification}`)}</span>{job.assessment.expired && <span className="career-danger">{t("status.expired")}</span>}</div>
        <p className="career-salary">{job.salary.text || t("salaryUnknown")}</p>
        {job.salary.text && <p className="career-muted">{t(`salaryKind.${job.salary.kind}`)}</p>}
        {job.source_received_at && <p className="career-muted">{t("received")}: {new Date(job.source_received_at).toLocaleString(i18n.language)}</p>}
        {job.deadline && <p>{t("deadline")}: {job.deadline}</p>}
        <div className="career-evidence"><h4>{t("strengths")}</h4>{job.assessment.strengths.length ? <ul>{job.assessment.strengths.map((s, i) => <li key={i}>{t(s.kind)}: {s.evidence.join(", ")}</li>)}</ul> : <p>{t("noEvidence")}</p>}
          <h4>{t("gaps")}</h4><ul>{[...job.assessment.gaps, ...job.assessment.checks].map((s, i) => <li key={i}>{bilingual(s)}</li>)}</ul>
          <p>{bilingual(job.assessment.next_step)}</p>
        </div>
        <details><summary>{t("sourceText")}</summary><pre className="career-source">{job.description}</pre></details>
        <div className="career-actions">
          <a href={job.url} target="_blank" rel="noopener noreferrer">{t("openJob")}</a>
          <button disabled={busy} onClick={() => void act(async () => { await request(`/jobs/${job.id}/verify`, "POST"); await load(); })}>{t("verify")}</button>
          <button disabled={busy} onClick={() => void act(async () => { const result = await request<{ text: string }>(`/jobs/${job.id}/draft`, "POST"); setDraft(result.text); })}>{t("draft")}</button>
          <label className="career-status-label">{t("applicationStatus")}<select value={job.status} disabled={busy} onChange={e => {
            const status = e.target.value;
            void act(async () => { await request(`/jobs/${job.id}/status`, "PATCH", { status }); await load(); });
          }}>{states.map(s => <option key={s} value={s}>{t(`status.${s}`)}</option>)}</select></label>
        </div>
      </article>)}</div>
      {draft && <section className="career-panel" aria-label={t("draft")}><h2>{t("draft")}</h2><p>{t("draftNote")}</p><label>{t("draftText")}<textarea className="career-draft" value={draft} onChange={e => setDraft(e.target.value)} /></label><button onClick={() => setDraft("")}>{t("close")}</button></section>}
    </>}
  </section>;
}
