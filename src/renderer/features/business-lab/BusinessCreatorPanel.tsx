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
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void request<{ capabilities: Capability[] }>("/capabilities")
      .then(data => { if (active) setItems(data.capabilities); })
      .catch(() => { if (active) setError("تعذر تحميل أنواع المشاريع"); });
    return () => { active = false; };
  }, []);
  const submit = async (execute: boolean) => {
    setBusy(true); setError(""); setPlan(null); setProjectId(""); setProjectPhase(""); setProjectError("");
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
        if (!cancelled) { setProjectPhase(data.phase); setProjectError(data.error_message ?? ""); }
      } catch {
        if (!cancelled) setProjectPhase("تعذر قراءة حالة المشروع");
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), 5000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [projectId, projectPhase]);
  return (
    <section aria-label="Business Creator" style={{ padding: 12, borderBottom: "1px solid var(--b1,#e5e7eb)" }}>
      <strong>إنشاء مشروع رقمي</strong>
      <select aria-label="نوع المشروع" value={capability} disabled={busy} onChange={e => { setCapability(e.target.value); setPlan(null); setError(""); }}
        style={{ display: "block", width: "100%", marginTop: 8 }}>
        {items.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      <textarea aria-label="وصف المشروع" value={description} disabled={busy} onChange={e => { setDescription(e.target.value); setPlan(null); setError(""); }}
        placeholder="صف المشروع الذي تريد إنشاءه" rows={3}
        style={{ display: "block", width: "100%", boxSizing: "border-box", marginTop: 8 }} />
      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <button type="button" disabled={busy || description.trim().length < 10} onClick={() => void submit(false)}>تخطيط</button>
        <button type="button" disabled={busy || description.trim().length < 10 || !["app", "store"].includes(capability)}
          onClick={() => void submit(true)}>بدء الإنشاء</button>
      </div>
      {plan && <p role="status">الخطة فقط — لم يبدأ التنفيذ. المحرك: {plan.engine}. المخرجات: {plan.expected_deliverables.join(", ")}</p>}
      {projectId && <p role="status">تم إرسال المشروع إلى SaaS Factory. المعرف: {projectId}. الحالة: {projectPhase || "جارٍ التحميل"}</p>}
      {projectError && <p role="alert">فشل المشروع: {projectError}</p>}
      {projectPhase === "PENDING_REVIEW" && <p role="status">المشروع ينتظر مراجعة أمنية قبل الاستكمال.</p>}
      {error && <p role="alert">{error}</p>}
      {!["app", "store"].includes(capability) && <small>التنفيذ غير متاح بعد لهذا النوع؛ التخطيط متاح.</small>}
    </section>
  );
}
