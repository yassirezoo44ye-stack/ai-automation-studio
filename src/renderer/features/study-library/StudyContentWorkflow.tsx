import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useOrg } from "../../contexts/OrgContext";
import { apiFetch } from "../../utils/api";

type Content = { voiceover: string; tiktok: string; instagram: string; youtube: string; video_url: string };
type Workflow = { id: string; title: string; lesson_slug: string; revision: number; state: "draft" | "reviewed" | "handed_off"; content: Content };
type Connection = { platform: string; implemented: boolean; configured: boolean; accounts: (string | null)[] };
type Post = { id: string; platform: string; status: string };
type Lesson = { slug: string; title: string; description: string };
const ROOT = "/api/study-library/workflows";
const names: Record<string, string> = { tiktok: "TikTok", instagram: "Instagram", youtube: "YouTube" };
const states = { draft: "مسودة", reviewed: "اعتُمدت هذه النسخة", handed_off: "أُنشئت مسودات الناشر" };
const empty: Content = { voiceover: "", tiktok: "", instagram: "", youtube: "", video_url: "" };
async function call<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await apiFetch(path, options); const body = await res.json();
  if (!res.ok) throw new Error(res.status === 409 ? "تغيرت النسخة أو سبق تحويلها. حدّث المسار قبل المتابعة." : res.status === 403 ? "يتطلب هذا المسار إدارة المكتبة وصلاحية إدارة مساحة العمل." : "تعذّر تنفيذ الخطوة. تحقق من الحقول والاتصال ثم أعد المحاولة.");
  return body as T;
}

function Editor({ workflow, lessons, onSaved }: { workflow: Workflow | null; lessons: Lesson[]; onSaved: (id: string) => void }) {
  const [slug, setSlug] = useState(workflow?.lesson_slug ?? lessons[0]?.slug ?? "");
  const [value, setValue] = useState<Content>(workflow?.content ?? empty);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [posts, setPosts] = useState<Post[] | null>(null);
  const dirty = !workflow || JSON.stringify(value) !== JSON.stringify(workflow.content);
  const locked = workflow?.state === "handed_off";
  const change = (key: keyof Content, text: string) => { setValue(v => ({ ...v, [key]: text })); setChecked(false); };
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setNotice("");
    try {
      const result = await call<Workflow>(workflow ? `${ROOT}/${workflow.id}` : ROOT, { method: workflow ? "PUT" : "POST", body: JSON.stringify({ ...value, ...(workflow ? { revision: workflow.revision } : { lesson_slug: slug }) }) });
      onSaved(result.id);
    } catch (error) { setNotice(error instanceof Error ? error.message : "تعذّر الحفظ."); } finally { setBusy(false); }
  }
  async function action(step: "review" | "handoff") {
    if (!workflow) return; setBusy(true); setNotice("");
    try {
      await call(`${ROOT}/${workflow.id}/${step}`, { method: "POST", body: JSON.stringify({ revision: workflow.revision }) });
      onSaved(workflow.id);
    } catch (error) { setNotice(error instanceof Error ? error.message : "تعذّر تنفيذ الخطوة."); } finally { setBusy(false); }
  }
  async function importContent(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      if (file.size > 512 * 1024) throw new Error("ملف المحتوى أكبر من الحد المسموح.");
      const input: unknown = JSON.parse(await file.text());
      if (!Array.isArray(input)) throw new Error("اختر ملف lesson-content.json الذي يحتوي قائمة الدروس.");
      const lesson = input.find((item: unknown) => typeof item === "object" && item !== null && "slug" in item && item.slug === slug) as Record<string, unknown> | undefined;
      if (!lesson || typeof lesson.voiceover !== "string" || typeof lesson.desc !== "string") throw new Error("لم نجد نص هذا الملخص داخل الملف. راجع المعرّف المختار.");
      setValue(v => ({ ...v, voiceover: String(lesson.voiceover), tiktok: String(lesson.desc), instagram: String(lesson.desc), youtube: String(lesson.desc) })); setChecked(false); setNotice("أُدرج النص محليًا. راجعه وعدّل وصف كل منصة ثم احفظ.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "تعذّر قراءة الملف."); } finally { setBusy(false); }
  }
  async function loadPosts() {
    if (!workflow) return; setBusy(true); setNotice("");
    try { const result = await call<{ posts: Post[] }>(`${ROOT}/${workflow.id}/posts`); setPosts(result.posts); }
    catch (error) { setNotice(error instanceof Error ? error.message : "تعذّر تحميل حالة المسودات."); } finally { setBusy(false); }
  }
  return <section className="study-workflow-editor" aria-label="تحرير مسار المحتوى">
    <h3>{workflow ? workflow.title : "مسار جديد من ملخص موجود"}</h3>
    <p>{workflow ? `${states[workflow.state]} · النسخة ${workflow.revision}` : "أضف الملخص عبر إدارة المكتبة أولًا، ثم اختره هنا. تظهر هنا ملخصات نتائج البحث الحالية."}</p>
    <form onSubmit={event => void save(event)}>
      <fieldset disabled={busy || locked}>
        {!workflow && <label>الملخص المصدر<select required value={slug} onChange={event => { setSlug(event.target.value); setValue(empty); setChecked(false); }}><option value="">اختر ملخصًا</option>{lessons.map(l => <option key={l.slug} value={l.slug}>{l.title}</option>)}</select></label>}
        <label>استيراد النص من حزمة المحتوى · اختياري<input type="file" accept="application/json,.json" onChange={event => void importContent(event.target.files?.[0])} /></label>
        <label>نص التعليق الصوتي<textarea required maxLength={12000} rows={5} value={value.voiceover} onChange={e => change("voiceover", e.target.value)} /></label>
        {(["tiktok", "instagram", "youtube"] as const).map(platform => <label key={platform}>وصف {names[platform]}<textarea required maxLength={2000} rows={3} value={value[platform]} onChange={e => change(platform, e.target.value)} /></label>)}
        <label>رابط الفيديو النهائي · HTTPS<input type="url" maxLength={2000} value={value.video_url} onChange={e => change("video_url", e.target.value)} dir="ltr" placeholder="https://media.example.com/lesson.mp4" /></label>
        <p className="study-small">النص ليس تسجيلًا أو فيديو. أضف رابط الملف النهائي بعد إنتاجه. لا تضع رابط PDF المدفوع في هذا الحقل.</p>
        <button className="study-primary" type="submit" disabled={!dirty}>حفظ مسودة المحتوى</button>
      </fieldset>
    </form>
    {workflow && !locked && <div className="study-workflow-actions">
      <label><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} disabled={busy || dirty} />راجعت الملخص والنص والفيديو وحقوق استخدامه</label>
      <button className="study-secondary" onClick={() => void action("review")} disabled={busy || dirty || !checked || !value.video_url}>اعتماد هذه النسخة</button>
      <button className="study-primary" onClick={() => void action("handoff")} disabled={busy || dirty || workflow.state !== "reviewed"}>إنشاء مسودات في ناشر المنصات</button>
      {dirty && <p>احفظ تعديلاتك أولًا؛ كل تعديل يلغي اعتماد النسخة السابقة.</p>}
    </div>}
    {locked && <div><p>أُرسلت المادة إلى قائمة مسودات الناشر. لم يُنفّذ نشر خارجي.</p><button className="study-secondary" onClick={() => void loadPosts()} disabled={busy}>تحديث حالة مسودات الناشر</button></div>}
    {posts && <ul>{posts.map(post => <li key={post.id}>{names[post.platform]} · {post.status === "draft" ? "مسودة، لم تُنشر" : post.status} <small dir="ltr">{post.id}</small></li>)}</ul>}
    <p role="status">{notice}</p>
  </section>;
}

function WorkspaceWorkflow({ lessons }: { lessons: Lesson[] }) {
  const [result, setResult] = useState<{ workflows: Workflow[]; connections: Connection[] } | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [auth, setAuth] = useState<{ platform: string; url: string; ticket: string } | null>(null);
  const [connecting, setConnecting] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([call<{ workflows: Workflow[] }>(ROOT, { signal: controller.signal }), call<{ platforms: Connection[] }>(`${ROOT}/connections`, { signal: controller.signal })]).then(([work, connections]) => {
      if (!controller.signal.aborted) { setResult({ workflows: work.workflows, connections: connections.platforms }); setError(""); }
    }).catch(error => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "تعذّر تحميل المسار."); });
    return () => controller.abort();
  }, [refresh]);
  async function connect(platform: string) {
    setConnecting(true); setError(""); setAuth(null);
    try {
      const result = await call<{ auth_url: string; ticket: string }>(`/api/social/accounts/${platform}/connect`);
      const url = new URL(result.auth_url); if (url.protocol !== "https:") throw new Error("رابط اتصال غير صالح.");
      if (!/^[a-f0-9]{32}$/.test(result.ticket)) throw new Error("تعذّر إنشاء خطوة الربط.");
      setAuth({ platform, url: url.href, ticket: result.ticket });
    } catch (error) { setError(error instanceof Error ? error.message : "تعذّر بدء الربط."); } finally { setConnecting(false); }
  }
  const current = result?.workflows.find(w => w.id === selected) ?? null;
  return <div className="study-content-workflow">
    <h2>من المكتبة إلى المنصات</h2><p>ملخص موجود ← نصوص محفوظة ← مراجعة النسخة ← فيديو نهائي ← مسودات الناشر. إنشاء المسودات لا ينشر الفيديو.</p>
    <button className="study-secondary" onClick={() => setRefresh(n => n + 1)}>تحديث المسار والاتصالات</button>
    {error && <p role="alert">{error}</p>}
    {result && <>
      <div className="study-workflow-connections">{result.connections.map(c => <article key={c.platform}><strong>{names[c.platform]}</strong><p>{!c.implemented ? "مزوّد النشر غير متاح بعد" : !c.configured ? "يحتاج إعداد خدمة المنصة" : c.accounts.length ? "حساب محفوظ · تحقق من صلاحيته قبل النشر" : "مهيّأ · يحتاج ربط حساب"}</p>{c.implemented && c.configured && <button className="study-secondary" disabled={connecting} onClick={() => void connect(c.platform)}>ربط حساب {names[c.platform]}</button>}</article>)}</div>
      {auth && <form action={auth.url} method="post" target="_blank" rel="noopener"><input type="hidden" name="ticket" value={auth.ticket} /><button className="study-primary" type="submit">متابعة ربط {names[auth.platform]} في نافذة جديدة ↗</button><p className="study-small">ابدأ هذه الخطوة خلال دقيقة، ثم عد وحدّث الاتصالات.</p></form>}
      <label>مسار محفوظ<select value={selected ?? ""} onChange={e => setSelected(e.target.value || null)}><option value="">إنشاء مسار جديد</option>{result.workflows.map(w => <option key={w.id} value={w.id}>{w.title} · {states[w.state]}</option>)}</select></label>
      {selected && !current ? <p role="status">جارٍ تحميل المسار المحفوظ…</p> : <Editor key={`${selected ?? "new"}-${current?.revision ?? 0}-${current?.state ?? "draft"}`} workflow={current} lessons={lessons} onSaved={id => { setSelected(id); setRefresh(n => n + 1); }} />}
    </>}
  </div>;
}
export function StudyContentWorkflow({ lessons }: { lessons: Lesson[] }) {
  const { currentOrgId } = useOrg();
  return <details className="study-publisher"><summary>إدارة المحتوى · ربط المكتبة والمنصات</summary>{currentOrgId ? <WorkspaceWorkflow key={currentOrgId} lessons={lessons} /> : <p>اختر مساحة عمل أولًا لإدارة مسودات المحتوى واتصالات المنصات.</p>}</details>;
}
