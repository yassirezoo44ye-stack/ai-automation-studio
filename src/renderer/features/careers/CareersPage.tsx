import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { useOrg } from "../../contexts/OrgContext";
import { APIError, apiFetch, parseJSON } from "../../shared/utils/api";
import "./careers.css";

type ListKey = "roles" | "skills" | "sectors" | "languages" | "cities";
type Profile = {
  summary: string; roles: string[]; sectors: string[]; skills: string[]; languages: string[]; cities: string[];
  experience_years: number | null; minimum_monthly_aed: number | null; uae_driving_license: boolean | null;
};
type Connection = { configured: boolean; connected: boolean; enabled: boolean; interval_hours: number; last_sync: string | null; last_error: string | null };
type AiFit = { summary: string; strengths: string[]; gaps: string[]; questions: string[]; stale?: boolean };
type Job = {
  id: string; title: string; company: string; location: string; url: string; status: string;
  description: string; source_received_at?: string | null; verification: string; deadline: string | null; source: string;
  extracted_by?: string; ai_fit?: AiFit;
  salary: { text: string | null; kind: string; period: string; min: number | null; max: number | null };
  assessment: { score: number; expired: boolean; strengths: { kind: string; evidence: string[] }[]; gaps: string[]; checks: string[]; next_step: string };
};
type Draft = { jobId: string; title: string; text: string; ai: boolean };
const emptyProfile: Profile = { summary: "", roles: [], sectors: [], skills: [], languages: [], cities: [], experience_years: null, minimum_monthly_aed: null, uae_driving_license: null };
const states = ["new", "saved", "applied", "interview", "rejected"];
const listKeys: ListKey[] = ["roles", "skills", "sectors", "languages", "cities"];
const checkable = new Set(["linkedin", "indeed"]);

function merge(current: string[], incoming: string[]) {
  const seen = new Set(current.map(v => v.toLocaleLowerCase()));
  return [...current, ...incoming.filter(v => !seen.has(v.toLocaleLowerCase()))];
}

function jumpTo(id: string) {
  document.getElementById(id)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

export function CareersPage() {
  const { currentOrgId } = useOrg();
  const { t } = useTranslation("careers");
  if (!currentOrgId) return <div className="career-workspace"><p>{t("chooseOrg")}</p></div>;
  return <CareerWorkspace key={currentOrgId} orgId={currentOrgId} />;
}

function ChipInput({ label, values, onChange, hint }: { label: string; values: string[]; onChange: (v: string[]) => void; hint: string }) {
  const { t } = useTranslation("careers");
  const id = useId();
  const [entry, setEntry] = useState("");
  function commit(raw: string) {
    const parts = raw.split(/[,،\n]/).map(s => s.trim()).filter(Boolean);
    if (parts.length) onChange(merge(values, parts));
    setEntry("");
  }
  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === "," || e.key === "،") { e.preventDefault(); commit(entry); }
    else if (e.key === "Backspace" && !entry && values.length) onChange(values.slice(0, -1));
  }
  return <div className="career-chip-field">
    <label htmlFor={id}>{label}</label>
    <div className="career-chip-box">
      {values.map(v => <span className="career-chip" key={v}>{v}
        <button type="button" aria-label={t("removeChip", { value: v })} onClick={() => onChange(values.filter(x => x !== v))}>×</button>
      </span>)}
      <input id={id} value={entry} placeholder={values.length ? "" : hint} onChange={e => {
        const value = e.target.value;
        if (/[,،]/.test(value)) commit(value); else setEntry(value);
      }} onKeyDown={onKeyDown} onBlur={() => entry.trim() && commit(entry)} />
    </div>
  </div>;
}

function ScoreRing({ score, expired }: { score: number; expired: boolean }) {
  const { t } = useTranslation("careers");
  const band = expired ? "off" : score >= 60 ? "high" : score >= 30 ? "mid" : "low";
  return <div className={`career-ring career-ring-${band}`} style={{ "--score": expired ? 0 : score } as CSSProperties}
    role="img" aria-label={t("scoreLabel", { score })}>
    <span>{score}</span>
  </div>;
}

function CareerWorkspace({ orgId }: { orgId: string }) {
  const { t, i18n } = useTranslation("careers");
  const [profile, setProfile] = useState<Profile>(emptyProfile);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [text, setText] = useState("");
  const [cv, setCv] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("match");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const exchangeStarted = useRef(false);
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

  useEffect(() => {
    if (!draft) return;
    const close = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") setDraft(null); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [draft]);

  async function act(name: string, work: () => Promise<void>, ai = false) {
    if (busy) return;
    setBusy(name); setError(""); setNotice("");
    try { await work(); }
    catch (e) {
      // AI routes answer 502 when the model's answer is unusable and 429 on quota.
      if (ai && e instanceof APIError && e.details.status === 502) setError(t("aiFailed"));
      else if (ai && e instanceof APIError && e.details.status === 429) setError(t("aiQuota"));
      else setError(e instanceof Error ? e.message : t("failed"));
    }
    finally { setBusy(null); }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (!params.has("state") || exchangeStarted.current) return;
    const expected = sessionStorage.getItem("flow-career-oauth-org");
    // Do not consume another workspace's one-time callback.
    if (expected !== orgId) return;
    exchangeStarted.current = true;
    const code = params.get("code"), state = params.get("state");
    window.history.replaceState(null, "", "/careers");
    sessionStorage.removeItem("flow-career-oauth-org");
    void Promise.resolve().then(async () => {
      if (params.has("error") || !code) throw new Error(t("consentDenied"));
      setBusy("gmail");
      await request("/gmail/exchange", "POST", { code, state });
    })
      .then(() => load()).then(() => setNotice(t("connected")))
      .catch(e => setError(e instanceof Error ? e.message : t("failed")))
      .finally(() => setBusy(null));
  }, [orgId, request, load, t]);

  const needle = query.trim().toLocaleLowerCase();
  const inView = (j: Job, f: string) => f === "all" || (f === "expired" ? j.assessment.expired : j.status === f);
  const visible = jobs.filter(j => inView(j, filter) && (!needle || `${j.title} ${j.company} ${j.location}`.toLocaleLowerCase().includes(needle)));
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
  const profileReady = Boolean(profile.summary.trim() || profile.roles.length || profile.skills.length);
  const shortlisted = jobs.filter(j => ["saved", "applied", "interview"].includes(j.status)).length;
  const steps = [
    { id: "career-profile", label: t("step.profile"), done: profileReady },
    { id: "career-add", label: t("step.add"), done: jobs.length > 0 },
    { id: "career-shortlist", label: t("step.shortlist"), done: shortlisted > 0 },
  ];
  const working = busy !== null;

  async function openDraft(job: Job, ai: boolean) {
    const result = await request<{ text: string }>(`/jobs/${job.id}/${ai ? "ai-draft" : "draft"}`, "POST");
    setDraft({ jobId: job.id, title: job.title, text: result.text, ai });
  }

  return <section className="career-workspace" aria-busy={working || loading} dir={i18n.dir()}>
    <header className="career-hero">
      <div>
        <span className="career-eyebrow">FLOW · CAREERS <b className="career-ai-badge">AI</b></span>
        <h1>{t("title")}</h1><p>{t("subtitle")}</p>
      </div>
      <div className="career-stats">
        <span className="career-count">{t("jobCount", { count: jobs.length })}</span>
        <span className="career-count">{t("shortlistedCount", { count: shortlisted })}</span>
      </div>
    </header>

    <nav className="career-steps" aria-label={t("step.nav")}>
      {steps.map((s, i) => <button type="button" key={s.id} className={s.done ? "is-done" : ""} onClick={() => jumpTo(s.id)}>
        <span className="career-step-num" aria-hidden="true">{s.done ? "✓" : i + 1}</span>{s.label}
      </button>)}
    </nav>

    {error && <div className="career-alert career-error" role="alert">{error}<button onClick={() => void act("load", load)} disabled={working}>{t("retry")}</button></div>}
    {notice && <div className="career-alert" role="status">{notice}</div>}

    {loading ? <div className="career-skeleton" role="status"><span className="career-sr">{t("loading")}</span><div /><div /><div /></div> : <>
      <div className="career-setup">
        <section id="career-profile" className="career-panel" aria-labelledby="career-profile-title">
          <h2 id="career-profile-title"><span className="career-step-num" aria-hidden="true">1</span>{t("profile")}</h2>

          <div className="career-ai-box">
            <h3><b className="career-ai-badge">AI</b>{t("aiProfileTitle")}</h3>
            <p className="career-muted">{t("aiProfileHint")}</p>
            <label>{t("cvLabel")}<textarea maxLength={30000} value={cv} onChange={e => setCv(e.target.value)} placeholder={t("cvPlaceholder")} /></label>
            <button type="button" className="career-ai-button" disabled={working || cv.trim().length < 20} onClick={() => void act("profile-ai", async () => {
              const result = await request<{ profile: Profile }>("/profile/extract", "POST", { text: cv });
              const ai = result.profile;
              setProfile(p => {
                const lists = Object.fromEntries(listKeys.map(k => [k, merge(p[k], ai[k])])) as Pick<Profile, ListKey>;
                return {
                  ...p, ...lists,
                  summary: ai.summary.trim() ? ai.summary : p.summary,
                  experience_years: ai.experience_years ?? p.experience_years,
                };
              });
              setNotice(t("aiFilled"));
            }, true)}>{busy === "profile-ai" ? t("aiWorking") : t("aiFill")}</button>
          </div>

          <form onSubmit={e => { e.preventDefault(); void act("profile", async () => {
            await request("/profile", "PUT", profile);
            await load(); setNotice(t("saved"));
          }); }}>
            <label>{t("summary")}<textarea maxLength={6000} value={profile.summary} onChange={e => setProfile({ ...profile, summary: e.target.value })} /></label>
            <p className="career-muted">{t("keywordsHint")}</p>
            {listKeys.map(k => <ChipInput key={k} label={t(k)} hint={t("chipHint")} values={profile[k]} onChange={v => setProfile(p => ({ ...p, [k]: v }))} />)}
            <div className="career-fields">
              <label>{t("years")}<input type="number" min="0" max="60" step="0.5" value={profile.experience_years ?? ""} onChange={e => setProfile({ ...profile, experience_years: e.target.value === "" ? null : Number(e.target.value) })} /></label>
              <label>{t("minimumSalary")}<input type="number" min="0" max="1000000" value={profile.minimum_monthly_aed ?? ""} onChange={e => setProfile({ ...profile, minimum_monthly_aed: e.target.value === "" ? null : Number(e.target.value) })} /></label>
              <label>{t("license")}<select value={profile.uae_driving_license === null ? "unknown" : String(profile.uae_driving_license)} onChange={e => setProfile({ ...profile, uae_driving_license: e.target.value === "unknown" ? null : e.target.value === "true" })}>
                <option value="unknown">{t("unknown")}</option><option value="true">{t("yes")}</option><option value="false">{t("no")}</option>
              </select></label>
            </div>
            <button className="career-primary" disabled={working}>{t("saveProfile")}</button>
          </form>
        </section>

        <section id="career-add" className="career-panel" aria-labelledby="career-add-title">
          <h2 id="career-add-title"><span className="career-step-num" aria-hidden="true">2</span>{t("addJobs")}</h2>
          <form onSubmit={e => { e.preventDefault(); void act("import", async () => {
            const result = await request<{ inserted: number; warning: string | null; method?: string }>("/import", "POST", { text, source: "manual", use_ai: true });
            await load();
            setNotice(result.warning ? bilingual(result.warning) : t(result.method === "ai" ? "importedAi" : "imported", { count: result.inserted }));
          }, true); }}>
            <h3>{t("pasteTitle")}</h3>
            <label>{t("pasteLabel")}<textarea maxLength={200000} required value={text} onChange={e => setText(e.target.value)} placeholder={t("pasteHint")} /></label>
            <p className="career-muted"><b className="career-ai-badge">AI</b> {t("pasteAiNote")}</p>
            <button className="career-primary" disabled={working || !text.trim()}>{busy === "import" ? t("aiWorking") : t("import")}</button>
          </form>
          <hr />
          <h3>{t("inbox")}</h3><p className="career-muted">{t("gmailDescription")}</p>
          {!connection?.configured && <p className="career-muted">{t("gmailNotConfigured")}</p>}
          {connection?.last_error && <p role="alert">{connection.last_error}</p>}
          <div className="career-actions">
            <button disabled={working || !connection?.configured} onClick={() => void act("gmail", async () => {
              const result = await request<{ url: string }>("/gmail/connect", "POST");
              sessionStorage.setItem("flow-career-oauth-org", orgId);
              window.location.assign(result.url);
            })}>{t(connection?.connected ? "reconnect" : "connect")}</button>
            {connection?.connected && <>
              <button disabled={working} onClick={() => void act("sync", async () => {
                const result = await request<{ inserted: number; busy: boolean; unparsed_messages: number }>("/gmail/sync", "POST");
                await load(); setNotice(result.busy ? t("syncBusy") : t("imported", { count: result.inserted }) + (result.unparsed_messages ? " " + t("unparsed", { count: result.unparsed_messages }) : ""));
              })}>{t("sync")}</button>
              <button disabled={working} onClick={() => void act("gmail", async () => { await request("/gmail", "DELETE"); await load(); })}>{t("disconnect")}</button>
            </>}
          </div>
          {connection?.connected && <>
            <label className="career-checkbox"><input type="checkbox" checked={connection.enabled} disabled={working} onChange={e => {
              const enabled = e.target.checked;
              void act("schedule", async () => { await request("/gmail/schedule", "PUT", { enabled, interval_hours: 24 }); await load(); });
            }} />{t("dailySync")}</label>
            {connection.last_sync && <p className="career-muted">{t("lastSync")}: {new Date(connection.last_sync).toLocaleString(i18n.language)}</p>}
          </>}
        </section>
      </div>

      <section id="career-shortlist" aria-labelledby="career-shortlist-title">
        <div className="career-toolbar">
          <h2 id="career-shortlist-title"><span className="career-step-num" aria-hidden="true">3</span>{t("opportunities")}</h2>
          <label className="career-search">{t("search")}<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder={t("searchHint")} /></label>
          <label>{t("sort")}<select value={sort} onChange={e => setSort(e.target.value)}><option value="match">{t("match")}</option><option value="salary">{t("salarySort")}</option></select></label>
        </div>
        <div className="career-tabs" role="group" aria-label={t("filter")}>
          {["all", ...states, "expired"].map(s => <button type="button" key={s} aria-pressed={filter === s} onClick={() => setFilter(s)}>
            {s === "all" ? t("all") : t(`status.${s}`)}<span>{jobs.filter(j => inView(j, s)).length}</span>
          </button>)}
        </div>
        <p className="career-muted">{t("rankingNote")}</p>
        {jobs.length >= 500 && <p role="status">{t("limitNote")}</p>}
        {!visible.length && <div className="career-panel career-empty">
          <p>{jobs.length ? t("emptyFilter") : t("empty")}</p>
          {!jobs.length && <button type="button" className="career-primary" onClick={() => jumpTo("career-add")}>{t("emptyAction")}</button>}
        </div>}
        <div className="career-jobs">{visible.map(job => <article className={`career-panel career-job${job.assessment.expired ? " is-expired" : ""}`} key={job.id}>
          <div className="career-job-title">
            <ScoreRing score={job.assessment.score} expired={job.assessment.expired} />
            <div><h3>{job.title}</h3><p>{job.company || t("unknownCompany")} · {job.location || t("unknown")}</p></div>
          </div>
          <div className="career-tags">
            <span>{job.source === "other" ? t("otherSource") : job.source}</span>
            <span>{t(`verification.${job.verification}`)}</span>
            {job.extracted_by === "ai" && <span className="career-tag-ai">{t("aiExtracted")}</span>}
            {job.assessment.expired && <span className="career-danger">{t("status.expired")}</span>}
          </div>
          <p className="career-salary">{job.salary.text || t("salaryUnknown")}</p>
          {job.salary.text && <p className="career-muted">{t(`salaryKind.${job.salary.kind}`)}</p>}
          {job.source_received_at && <p className="career-muted">{t("received")}: {new Date(job.source_received_at).toLocaleString(i18n.language)}</p>}
          {job.deadline && <p>{t("deadline")}: {job.deadline}</p>}

          <div className="career-evidence">
            <h4>{t("strengths")}</h4>
            {job.assessment.strengths.length
              ? <div className="career-chips">{job.assessment.strengths.flatMap(s => s.evidence.map(ev => <span className="career-chip is-good" key={s.kind + ev}>{t(s.kind)}: {ev}</span>))}</div>
              : <p className="career-muted">{t("noEvidence")}</p>}
            {(job.assessment.gaps.length > 0 || job.assessment.checks.length > 0) && <>
              <h4>{t("gaps")}</h4>
              <ul className="career-flags">
                {job.assessment.gaps.map(g => <li className="is-gap" key={g}>{bilingual(g)}</li>)}
                {job.assessment.checks.map(c => <li className="is-check" key={c}>{bilingual(c)}</li>)}
              </ul>
            </>}
            <p className="career-next">{bilingual(job.assessment.next_step)}</p>
          </div>

          <div className="career-fit">
            {job.ai_fit ? <>
              <h4><b className="career-ai-badge">AI</b>{t("fitTitle")}</h4>
              <p>{job.ai_fit.summary}</p>
              {job.ai_fit.strengths.length > 0 && <ul className="career-flags">{job.ai_fit.strengths.map(s => <li className="is-good" key={s}>{s}</li>)}</ul>}
              {job.ai_fit.gaps.length > 0 && <ul className="career-flags">{job.ai_fit.gaps.map(s => <li className="is-gap" key={s}>{s}</li>)}</ul>}
              {job.ai_fit.questions.length > 0 && <><h5>{t("fitQuestions")}</h5><ul className="career-flags">{job.ai_fit.questions.map(s => <li className="is-check" key={s}>{s}</li>)}</ul></>}
              <p className="career-muted">{job.ai_fit.stale ? t("fitStale") : t("fitNote")}</p>
            </> : <p className="career-muted">{t("fitIntro")}</p>}
            <button type="button" className="career-ai-button" disabled={working} onClick={() => void act(`fit-${job.id}`, async () => {
              const result = await request<{ ai_fit: AiFit }>(`/jobs/${job.id}/fit`, "POST", { language: i18n.language.startsWith("ar") ? "ar" : "en" });
              setJobs(list => list.map(j => j.id === job.id ? { ...j, ai_fit: result.ai_fit } : j));
            }, true)}>{busy === `fit-${job.id}` ? t("aiWorking") : t(job.ai_fit ? "fitRefresh" : "fitRun")}</button>
          </div>

          <details><summary>{t("sourceText")}</summary><pre className="career-source">{job.description}</pre></details>
          <div className="career-actions">
            <button className="career-primary" disabled={working} onClick={() => void act(`draft-${job.id}`, () => openDraft(job, true), true)}>{busy === `draft-${job.id}` ? t("aiWorking") : t("draftButton")}</button>
            {job.url && <a href={job.url} target="_blank" rel="noopener noreferrer">{t("openJob")}</a>}
            {checkable.has(job.source) && <button disabled={working} onClick={() => void act(`verify-${job.id}`, async () => { await request(`/jobs/${job.id}/verify`, "POST"); await load(); })}>{t("verify")}</button>}
            <label className="career-status-label">{t("applicationStatus")}<select value={job.status} disabled={working} onChange={e => {
              const status = e.target.value;
              void act("status", async () => { await request(`/jobs/${job.id}/status`, "PATCH", { status }); await load(); });
            }}>{states.map(s => <option key={s} value={s}>{t(`status.${s}`)}</option>)}</select></label>
          </div>
        </article>)}</div>
      </section>
    </>}

    {draft && <div className="career-drawer-backdrop">
      <div className="career-drawer" role="dialog" aria-modal="true" aria-label={t("draft")}>
        <header>
          <h2>{draft.ai && <b className="career-ai-badge">AI</b>}{t("draftFor", { title: draft.title })}</h2>
          <button type="button" onClick={() => setDraft(null)}>{t("close")}</button>
        </header>
        <p className="career-muted">{t("draftNote")}</p>
        <label>{t("draftText")}<textarea autoFocus className="career-draft" value={draft.text} onChange={e => setDraft({ ...draft, text: e.target.value })} /></label>
        <div className="career-actions">
          <button type="button" className="career-primary" onClick={() => void navigator.clipboard?.writeText(draft.text).then(() => setNotice(t("copied")))}>{t("copy")}</button>
          {draft.ai && <button type="button" disabled={working} onClick={() => {
            const job = jobs.find(j => j.id === draft.jobId);
            if (job) void act(`draft-${job.id}`, () => openDraft(job, false));
          }}>{t("useTemplate")}</button>}
        </div>
      </div>
    </div>}
  </section>;
}
