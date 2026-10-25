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
function headers(): HeadersInit {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${localStorage.getItem("auth_token") ?? ""}`,
  };
}
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(API + path, {
    method: body ? "POST" : "GET",
    headers: headers(),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

/** Embedded in Business Lab; never auto-publishes or purchases anything. */
export function BusinessCreatorPanel() {
  const [items, setItems] = useState<Capability[]>([]);
  const [capability, setCapability] = useState("app");
  const [description, setDescription] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [projectId, setProjectId] = useState("");
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
    setBusy(true); setError(""); setProjectId("");
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
  return (
    <section aria-label="Business Creator" style={{ padding: 12, borderBottom: "1px solid var(--b1,#e5e7eb)" }}>
      <strong>إنشاء مشروع رقمي</strong>
      <select aria-label="نوع المشروع" value={capability} onChange={e => { setCapability(e.target.value); setPlan(null); }}
        style={{ display: "block", width: "100%", marginTop: 8 }}>
        {items.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      <textarea aria-label="وصف المشروع" value={description} onChange={e => setDescription(e.target.value)}
        placeholder="صف المشروع الذي تريد إنشاءه" rows={3}
        style={{ display: "block", width: "100%", boxSizing: "border-box", marginTop: 8 }} />
      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <button type="button" disabled={busy || description.trim().length < 10} onClick={() => void submit(false)}>تخطيط</button>
        <button type="button" disabled={busy || description.trim().length < 10 || !["app", "store"].includes(capability)}
          onClick={() => void submit(true)}>بدء الإنشاء</button>
      </div>
      {plan && <p role="status">الخطة فقط — لم يبدأ التنفيذ. المحرك: {plan.engine}. المخرجات: {plan.expected_deliverables.join(", ")}</p>}
      {projectId && <p role="status">تم إرسال المشروع إلى SaaS Factory. المعرف: {projectId}</p>}
      {error && <p role="alert">{error}</p>}
      {!["app", "store"].includes(capability) && <small>التنفيذ غير متاح بعد لهذا النوع؛ التخطيط متاح.</small>}
    </section>
  );
}
