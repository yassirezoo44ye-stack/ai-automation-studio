import { apiFetch } from "../../shared/utils/api";
import { useEffect, useState } from "react";

type Capability = {
  id: string;
  title: string;
  engine: string;
  status: string;
};
type Plan = {
  status: string;
  engine: string;
  expected_deliverables: string[];
};
const API = "/api/business-creator";
const CAPABILITY_ICONS: Record<string, { icon: string; color: string; background: string }> = {
  content: { icon: "🎬", color: "#9D174D", background: "#FCE7F3" },
  digital_product: { icon: "📚", color: "#6D28D9", background: "#EDE9FE" },
  youtube: { icon: "▶️", color: "#B91C1C", background: "#FEE2E2" },
  store: { icon: "🛍️", color: "#047857", background: "#D1FAE5" },
  app: { icon: "🚀", color: "#4338CA", background: "#E0E7FF" },
  marketing: { icon: "📣", color: "#B45309", background: "#FEF3C7" },
  voiceover: { icon: "🎙️", color: "#0369A1", background: "#E0F2FE" },
  analytics: { icon: "📊", color: "#0F766E", background: "#CCFBF1" },
  freelance: { icon: "💼", color: "#7C3AED", background: "#F3E8FF" },
};
const CAPABILITY_LABELS: Record<string, string> = {
  app: "تطبيق أو موقع إلكتروني",
  store: "متجر إلكتروني",
  content: "صناعة المحتوى",
  digital_product: "منتجات رقمية",
  youtube: "إنتاج محتوى يوتيوب",
  marketing: "التسويق للأعمال",
  voiceover: "التعليق الصوتي",
  analytics: "تحليل البيانات",
  freelance: "خدمات العمل الحر",
};
const PHASE_LABELS: Record<string, string> = {
  IDEA: "استلام الفكرة",
  BLUEPRINT: "إعداد المخطط",
  BUILDING: "إنشاء المشروع",
  TESTING: "فحص مبدئي",
  VERIFYING: "مراجعة أمنية",
  DEPLOYING: "حفظ المشروع داخل Flow",
  LIVE: "مكتمل داخل Flow",
  FAILED: "فشل الإنشاء",
  PENDING_REVIEW: "بانتظار المراجعة",
};
const DEFAULT_ICON = { icon: "✨", color: "#4338CA", background: "#E0E7FF" };
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await apiFetch(API + path, {
    method: body ? "POST" : "GET",
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

/** Embedded in Business Lab; never auto-publishes or purchases anything. */
export function BusinessCreatorPanel() {
  const [items, setItems] = useState<Capability[]>([]);
  const [capability, setCapability] = useState("app");
  const [description, setDescription] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [projectId, setProjectId] = useState("");
  const [projectPhase, setProjectPhase] = useState("");
  const [projectError, setProjectError] = useState("");
  const [pollError, setPollError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const visual = CAPABILITY_ICONS[capability] ?? DEFAULT_ICON;
  const canSubmit = !busy && description.trim().length >= 10 && description.trim().length <= 3000;
  const canExecute = canSubmit && ["app", "store"].includes(capability);
  useEffect(() => {
    let active = true;
    void request<{ capabilities: Capability[] }>("/capabilities")
      .then(data => { if (active) setItems(data.capabilities); })
      .catch(() => { if (active) setError("تعذر تحميل أنواع المشاريع"); });
    return () => { active = false; };
  }, []);
  const submit = async (execute: boolean) => {
    setBusy(true); setError(""); setPlan(null); setProjectId(""); setProjectPhase(""); setProjectError(""); setPollError("");
    try {
      const body = { capability, description };
      if (execute) {
        const result = await request<{ project_id: string }>("/execute", body);
        setProjectId(result.project_id);
      } else {
        setPlan(await request<Plan>("/plan", body));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "تعذر تنفيذ الطلب");
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!projectId || ["LIVE", "FAILED", "PENDING_REVIEW"].includes(projectPhase)) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await apiFetch(`/api/saas-factory/projects/${encodeURIComponent(projectId)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json() as { phase: string; error_message?: string | null };
        if (!cancelled) { setProjectPhase(data.phase); setProjectError(data.error_message ?? ""); setPollError(""); }
      } catch {
        if (!cancelled) setPollError("تعذر تحديث حالة المشروع؛ ستتم إعادة المحاولة تلقائياً.");
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), 5000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [projectId, projectPhase]);
  return (
    <section aria-label="Business Creator" style={{ padding: 12, borderBottom: "1px solid var(--b1,#e5e7eb)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, direction: "rtl" }}>
        <span aria-hidden="true" style={{ display: "grid", placeItems: "center", width: 48, height: 48, flexShrink: 0, borderRadius: 14, background: visual.background, color: visual.color, fontSize: 26 }}>{visual.icon}</span>
        <div>
          <strong style={{ display: "block", fontSize: 18, color: "var(--t1,#111827)" }}>إنشاء مشروع رقمي</strong>
          <span style={{ fontSize: 13, color: "var(--t3,#6b7280)" }}>اختر الفكرة، راجع الخطة، ثم ابدأ الإنشاء</span>
        </div>
      </div>
      <label htmlFor="business-creator-capability" style={{ display: "block", marginTop: 12, fontWeight: 600, fontSize: 14, color: "var(--t1,#111827)" }}>نوع المشروع</label>
      <select id="business-creator-capability" aria-label="نوع المشروع" value={capability} disabled={busy} onChange={e => { setCapability(e.target.value); setPlan(null); setError(""); }}
        style={{ display: "block", width: "100%", minHeight: 46, marginTop: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--b1,#d1d5db)", background: "var(--bg-input,var(--bg-card,#fff))", color: "var(--t1,#111827)", fontSize: 14 }}>
        {items.map(item => <option key={item.id} value={item.id}>{CAPABILITY_ICONS[item.id]?.icon ?? "✨"} {CAPABILITY_LABELS[item.id] ?? item.title}</option>)}
      </select>
      <label htmlFor="business-creator-description" style={{ display: "block", marginTop: 12, fontWeight: 600, fontSize: 14, color: "var(--t1,#111827)" }}>وصف المشروع</label>
      <textarea id="business-creator-description" aria-label="وصف المشروع" value={description} disabled={busy} onChange={e => { setDescription(e.target.value); setPlan(null); setError(""); }}
        placeholder="صف المشروع الذي تريد إنشاءه" rows={3} maxLength={3000}
        style={{ display: "block", width: "100%", boxSizing: "border-box", marginTop: 10, padding: 12, borderRadius: 10, border: "1px solid var(--b1,#d1d5db)", background: "var(--bg-input,var(--bg-card,#fff))", color: "var(--t1,#111827)", fontSize: 14, fontFamily: "inherit", resize: "vertical" }} />
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 6, marginTop: 6, color: "var(--t3,#6b7280)", fontSize: 12 }}><span>أدخل 10 أحرف على الأقل. لا يتم نشر أي مشروع تلقائياً.</span><span aria-live="polite">{description.length} / 3000</span></div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 12, direction: "rtl" }}>
        <button type="button" disabled={!canSubmit} onClick={() => void submit(false)} style={{ minHeight: 46, flex: "1 1 140px", padding: "10px 16px", borderRadius: 10, border: "1px solid var(--b1,#d1d5db)", background: "var(--bg-card,#fff)", color: "var(--t1,#111827)", fontWeight: 600, cursor: "pointer" }}><span aria-hidden="true">🧭</span> {busy ? "جارٍ المعالجة…" : "تخطيط المشروع"}</button>
        <button type="button" disabled={!canExecute}
          onClick={() => void submit(true)} style={{ minHeight: 46, flex: "1 1 140px", padding: "10px 16px", borderRadius: 10, border: 0, background: "#4F46E5", color: "#fff", fontWeight: 700, cursor: "pointer" }}><span aria-hidden="true">🚀</span> {busy ? "جارٍ المعالجة…" : "بدء الإنشاء"}</button>
      </div>
      {plan && <p role="status" style={{ padding: 12, borderRadius: 10, background: "var(--bg-card,#fff)", border: "1px solid var(--b1,#e5e7eb)", color: "var(--t1,#111827)", overflowWrap: "anywhere" }}>الخطة فقط — لم يبدأ التنفيذ. المحرك: {plan.engine}. المخرجات: {plan.expected_deliverables.join(", ")}</p>}
      {projectId && <p role="status" style={{ padding: 12, borderRadius: 10, background: "var(--bg-card,#fff)", border: "1px solid var(--b1,#e5e7eb)", color: "var(--t1,#111827)", overflowWrap: "anywhere" }}>تم إرسال المشروع إلى SaaS Factory (مرحلة LIVE داخل Flow لا تعني نشره على الإنترنت). المعرف: {projectId}. الحالة: {PHASE_LABELS[projectPhase] ?? (projectPhase || "جارٍ التحميل")}</p>}
      {projectError && <p role="alert">خطأ المشروع: {projectError}</p>}
      {pollError && <p role="alert">{pollError}</p>}
      {projectPhase === "PENDING_REVIEW" && <p role="status">المشروع ينتظر مراجعة أمنية قبل الاستكمال.</p>}
      {error && <p role="alert" style={{ color: "var(--danger,#b91c1c)", overflowWrap: "anywhere" }}>{error}</p>}
      {!["app", "store"].includes(capability) && <small>التنفيذ غير متاح بعد لهذا النوع؛ التخطيط متاح.</small>}
    </section>
  );
}
