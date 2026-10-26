import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { API, apiFetch } from "../../utils/api";
import "./study-library.css";

type Lesson = { slug: string; title: string; subject: string; description: string; pages: number; published_at: string };
type Catalog = { lessons: Lesson[]; checkout_url: string | null };
type Membership = "guest" | "loading" | "active" | "locked" | "unverified" | "error";
const subjects = [["", "كل المواد", "✦"], ["math", "الرياضيات", "∑"], ["physics", "الفيزياء", "↗"], ["chemistry", "الكيمياء", "⚗"], ["biology", "الأحياء", "❋"], ["english", "الإنجليزية", "Aa"], ["computing", "الحاسوب", "⌘"]];

function Publisher({ onPublished }: { onPublished: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget;
    setBusy(true); setMessage("");
    try {
      const res = await apiFetch("/api/study-library/lessons", { method: "POST", body: new FormData(form) });
      const result = await res.json();
      if (!res.ok) throw new Error(typeof result.detail === "string" ? result.detail : "تعذّر إضافة الملخص.");
      setMessage(result.created ? "أُضيف الملخص إلى المكتبة." : "هذا الملخص موجود بالفعل.");
      form.reset(); onPublished();
    } catch (error) { setMessage(error instanceof Error ? error.message : "تعذّر إضافة الملخص."); }
    finally { setBusy(false); }
  }
  return <details className="study-publisher"><summary>إدارة المكتبة · إضافة ملخص</summary><form onSubmit={submit}>
    <label>العنوان<input name="title" required maxLength={160} /></label>
    <label>المعرّف الإنجليزي<input name="slug" required maxLength={80} pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="fractions-basics" dir="ltr" /></label>
    <label>المادة<select name="subject">{subjects.slice(1).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
    <label>الوصف<textarea name="description" required maxLength={1200} rows={3} /></label>
    <label>ملف PDF · حتى 8 ميجابايت<input name="pdf" type="file" accept="application/pdf" required /></label>
    <label>غلاف PNG · حتى 2 ميجابايت<input name="cover" type="file" accept="image/png" required /></label>
    <button className="study-primary" disabled={busy} type="submit">{busy ? "جارٍ الإضافة…" : "إضافة إلى المكتبة"}</button><p role="status">{message}</p>
  </form></details>;
}

export function StudyLibraryPage({ onSignIn }: { onSignIn?: () => void }) {
  const { user } = useAuth();
  const [catalogResult, setCatalogResult] = useState<{ key: string; data: Catalog | null; error: string } | null>(null);
  const [subject, setSubject] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [accessResult, setAccessResult] = useState<{ key: string; granted: boolean; admin: boolean; failed: boolean } | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const reload = () => setRefresh(r => r + 1);
  const requestKey = JSON.stringify([subject, query, offset, refresh]);
  const loading = catalogResult?.key !== requestKey;
  const catalog = loading ? null : catalogResult?.data;
  const error = loading ? "" : catalogResult?.error;
  const userId = user?.id;
  const emailVerified = user?.email_verified;
  const accessKey = JSON.stringify([userId, user?.email, emailVerified, refresh]);
  const membership: Membership = !userId ? "guest" : !emailVerified ? "unverified"
    : accessResult?.key !== accessKey ? "loading" : accessResult.failed ? "error"
      : accessResult.granted ? "active" : "locked";
  const isAdmin = membership === "active" && accessResult?.admin;

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ q: query, limit: "30", offset: String(offset) });
    if (subject) params.set("subject", subject);
    void apiFetch(`/api/study-library/catalog?${params}`, { signal: controller.signal }).then(async res => {
      if (!res.ok) throw new Error("catalog");
      const data: Catalog = await res.json();
      if (!controller.signal.aborted) setCatalogResult({ key: requestKey, data, error: "" });
    }).catch(() => { if (!controller.signal.aborted) setCatalogResult({ key: requestKey, data: null, error: "تعذّر تحميل الملخصات. تحقق من الاتصال ثم أعد المحاولة." }); });
    return () => controller.abort();
  }, [subject, query, offset, requestKey]);

  useEffect(() => {
    const controller = new AbortController();
    if (!userId || !emailVerified) return () => controller.abort();
    void apiFetch("/api/study-library/access", { signal: controller.signal }).then(async res => {
      if (!res.ok) throw new Error("access");
      const data = await res.json();
      if (!controller.signal.aborted) setAccessResult({ key: accessKey, granted: Boolean(data.has_access), admin: Boolean(data.is_admin), failed: false });
    }).catch(() => { if (!controller.signal.aborted) setAccessResult({ key: accessKey, granted: false, admin: false, failed: true }); });
    return () => controller.abort();
  }, [userId, emailVerified, accessKey]);

  async function download(lesson: Lesson) {
    setDownloading(lesson.slug); setNotice("");
    try {
      const res = await apiFetch(`/api/study-library/lessons/${encodeURIComponent(lesson.slug)}/download`);
      if (!res.ok) {
        if (res.status === 403) { setAccessResult({ key: accessKey, granted: false, admin: false, failed: false }); throw new Error("لم تتأكد صلاحية الشراء. أعد التحقق أو راجع بريد الشراء."); }
        throw new Error("تعذّر تنزيل الملف. أعد المحاولة.");
      }
      const url = URL.createObjectURL(await res.blob()); const link = document.createElement("a");
      link.href = url; link.download = `${lesson.slug}.pdf`; document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30000); setNotice(`بدأ تنزيل «${lesson.title}».`);
    } catch (cause) { setNotice(cause instanceof Error ? cause.message : "تعذّر تنزيل الملف."); }
    finally { setDownloading(null); }
  }
  const accessText: Record<Membership, string> = {
    guest: "سجّل الدخول بالبريد نفسه المستخدم للشراء، ثم افتح ملخصاتك.", loading: "جارٍ التحقق من صلاحية الدخول…",
    active: "مكتبتك مفتوحة. اختر ملخصًا وابدأ التعلّم.", locked: "اشتريت بالفعل؟ استخدم بريد الشراء نفسه، ثم اضغط إعادة التحقق.",
    unverified: "وثّق بريد حسابك أولًا من رسالة التحقق حتى نتمكن من مطابقة الشراء.", error: "تعذّر التحقق من صلاحية الدخول الآن. أعد المحاولة قبل إجراء شراء جديد.",
  };
  return <section className="study-library" dir="rtl" aria-label="مكتبة افهمها بصريًا">
    <header className="study-hero"><div className="study-eyebrow"><span className="study-dot" />مكتبة تعليمية بالعربية</div>
      <h1>افهمها <span>بصريًا.</span></h1><p className="study-intro">فكرة واضحة، مثال تتذكّره، وتدريب يثبّت المعلومة.<br />ملخصات صغيرة، لتمنح فهمك مساحة أكبر.</p>
      <div className="study-facts"><span>✦ ست مواد</span><span>PDF قابل للطباعة</span><span>أمثلة وأسئلة محلولة</span></div>
      <div className="study-orbit" aria-hidden="true"><span>∑</span><span>⚗</span><span>Aa</span><span>✦</span></div>
    </header>
    <section className={`study-access study-access-${membership}`} aria-label="دخول المكتبة">
      <div><strong>{membership === "active" ? "أهلًا بك في مكتبتك" : "كل ملخص، بداية لفهم جديد"}</strong><p>{accessText[membership]}</p></div>
      <div className="study-access-actions">
        {membership === "guest" && onSignIn && <button className="study-primary" onClick={onSignIn}>تسجيل الدخول</button>}
        {membership === "locked" && catalog?.checkout_url && <a className="study-primary" href={catalog.checkout_url} target="_blank" rel="noopener noreferrer">شراء دخول المكتبة ↗</a>}
        {membership === "locked" && catalog && !catalog.checkout_url && <span className="study-small">سيُتاح الشراء بعد تفعيل المتجر.</span>}
        {user && membership !== "unverified" && <button className="study-secondary" onClick={reload}>إعادة التحقق</button>}
      </div>
    </section>
    <section className="study-collection" aria-label="الملخصات التعليمية">
      <div className="study-section-title"><div><span className="study-eyebrow">تعلّم على طريقتك</span><h2>اختر فكرتك التالية</h2></div>
        <form role="search" onSubmit={event => { event.preventDefault(); setOffset(0); setQuery(search.trim()); }}>
          <label className="study-sr-only" htmlFor="study-search">ابحث عن ملخص</label><input id="study-search" value={search} maxLength={120} onChange={event => setSearch(event.target.value)} placeholder="عن ماذا تريد أن تتعلّم؟" /><button className="study-secondary" type="submit">بحث</button>
        </form>
      </div>
      <div className="study-filters" aria-label="تصفية حسب المادة">{subjects.map(([id, name, icon]) => <button key={id} aria-pressed={subject === id} onClick={() => { setSubject(id); setOffset(0); }}><span aria-hidden="true">{icon}</span>{name}</button>)}</div>
      <p role="status" className="study-notice">{notice}</p>
      {loading ? <div className="study-empty" role="status">جارٍ ترتيب الملخصات…</div> : error ? <div className="study-empty" role="alert"><p>{error}</p><button className="study-secondary" onClick={reload}>إعادة المحاولة</button></div>
        : !catalog?.lessons.length ? <div className="study-empty"><span aria-hidden="true">✦</span><h3>مساحة لفكرة جديدة</h3><p>{query || subject ? "لا توجد نتائج لهذه التصفية. جرّب مادة أو كلمة أخرى." : "لم تُضَف ملخصات إلى المكتبة بعد. ستظهر هنا عندما تُنشر."}</p></div>
        : <div className="study-grid">{catalog.lessons.map(lesson => <article key={lesson.slug} className={`study-card study-${lesson.subject}`}>
          <div className="study-cover"><img src={`${API}/api/study-library/lessons/${encodeURIComponent(lesson.slug)}/cover`} alt={`غلاف ${lesson.title}`} loading="lazy" /></div>
          <div className="study-card-content"><div className="study-card-meta"><span>{subjects.find(s => s[0] === lesson.subject)?.[1] ?? lesson.subject}</span><span>{lesson.pages} صفحات</span></div><h3>{lesson.title}</h3><p>{lesson.description}</p>
            <div className="study-card-bottom"><time dateTime={lesson.published_at}>{new Intl.DateTimeFormat("ar-AE", { day: "numeric", month: "short", timeZone: "Asia/Dubai" }).format(new Date(lesson.published_at))}</time><button className="study-secondary" disabled={membership !== "active" || downloading !== null} onClick={() => void download(lesson)}>{downloading === lesson.slug ? "جارٍ التنزيل…" : membership === "active" ? "تنزيل الملخص ↓" : "يتطلب دخول المكتبة"}</button></div>
          </div>
        </article>)}</div>}
      {!loading && !error && <div className="study-pagination"><button className="study-secondary" disabled={offset === 0} onClick={() => setOffset(o => Math.max(0, o - 30))}>السابق</button><button className="study-secondary" disabled={!catalog || catalog.lessons.length < 30} onClick={() => setOffset(o => o + 30)}>التالي</button></div>}
    </section>
    {isAdmin && <Publisher onPublished={reload} />}
    <footer className="study-footer"><strong>القليل كل مرة. فهم يبقى.</strong><p>ملخصات تأسيسية عامة، غير مرتبطة بمنهج أو صف محدد. للاستخدام الشخصي.</p></footer>
  </section>;
}
