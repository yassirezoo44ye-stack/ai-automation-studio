import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import * as contentApi from "../../api/content";
import { ApiError } from "../../api/client";
import type { ContentPillar, ContentStrategy, ContentStrategyInput } from "../../api/contentTypes";
import { useCurrentOrg } from "../../hooks/useCurrentOrg";

const EMPTY_FORM: ContentStrategyInput = {
  name: "",
  business_description: "",
  target_audience: "",
  goals: "",
  tone: "engaging",
  language: "english",
  brand_voice: "",
};

export function ContentStrategyPage() {
  const org = useCurrentOrg();
  const [strategies, setStrategies] = useState<ContentStrategy[]>([]);
  const [selected, setSelected] = useState<ContentStrategy | null>(null);
  const [pillars, setPillars] = useState<ContentPillar[]>([]);
  const [form, setForm] = useState<ContentStrategyInput>(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pillarName, setPillarName] = useState("");
  const [pillarDescription, setPillarDescription] = useState("");

  useEffect(() => {
    if (!org) return;
    contentApi
      .listStrategies(org.id)
      .then((list) => {
        setStrategies(list);
        if (list.length > 0) setSelected(list[0]);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load strategies"))
      .finally(() => setLoading(false));
  }, [org]);

  useEffect(() => {
    if (!org || !selected) {
      setPillars([]);
      return;
    }
    contentApi.listPillars(org.id, selected.id).then(setPillars).catch(() => setPillars([]));
  }, [org, selected]);

  if (!org) return <div className="center-loading">Loading…</div>;

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      const created = await contentApi.createStrategy(org.id, form);
      setStrategies((prev) => [created, ...prev]);
      setSelected(created);
      setForm(EMPTY_FORM);
      setShowForm(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create strategy");
    }
  };

  const handleAddPillar = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !pillarName.trim()) return;
    try {
      const pillar = await contentApi.createPillar(org.id, selected.id, {
        name: pillarName, description: pillarDescription || undefined,
      });
      setPillars((prev) => [...prev, pillar]);
      setPillarName("");
      setPillarDescription("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to add pillar");
    }
  };

  const handleDeletePillar = async (pillarId: string) => {
    if (!selected) return;
    await contentApi.deletePillar(org.id, pillarId);
    setPillars((prev) => prev.filter((p) => p.id !== pillarId));
  };

  return (
    <div className="page">
      <div className="dashboard">
        <h1>Content Strategy</h1>
        <p style={{ color: "var(--text-muted)" }}>
          Define your brand context once — every generation in{" "}
          <Link to="/content/generate">Generate</Link> uses it.
        </p>

        {error && <div className="error-banner">{error}</div>}

        <div className="section-title">Your strategies</div>
        {loading ? (
          <div className="notice-card">Loading…</div>
        ) : strategies.length === 0 && !showForm ? (
          <div className="notice-card">No strategies yet. Create one to start generating content.</div>
        ) : (
          <div className="org-list" style={{ marginBottom: "1rem" }}>
            {strategies.map((s) => (
              <button
                key={s.id}
                className="org-chip"
                style={{
                  cursor: "pointer",
                  border: selected?.id === s.id ? "1px solid var(--accent)" : undefined,
                  background: "transparent",
                }}
                onClick={() => setSelected(s)}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}

        <button className="btn btn-ghost" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ New Strategy"}
        </button>

        {showForm && (
          <form onSubmit={handleCreate} className="composer" style={{ marginTop: "1rem", textAlign: "left" }}>
            <div className="field">
              <label htmlFor="strategy-name">Name</label>
              <input
                id="strategy-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="business-description">Business description</label>
              <input
                id="business-description"
                value={form.business_description}
                onChange={(e) => setForm({ ...form, business_description: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="target-audience">Target audience</label>
              <input
                id="target-audience"
                value={form.target_audience}
                onChange={(e) => setForm({ ...form, target_audience: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="goals">Goals</label>
              <input id="goals" value={form.goals} onChange={(e) => setForm({ ...form, goals: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="brand-voice">Brand voice</label>
              <input
                id="brand-voice"
                value={form.brand_voice}
                onChange={(e) => setForm({ ...form, brand_voice: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="tone">Tone</label>
              <input id="tone" value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="language">Language</label>
              <input
                id="language"
                value={form.language}
                onChange={(e) => setForm({ ...form, language: e.target.value })}
              />
            </div>
            <button type="submit" className="btn btn-primary">
              Create Strategy
            </button>
          </form>
        )}

        {selected && (
          <>
            <div className="section-title">Content Pillars — {selected.name}</div>
            <div className="org-list" style={{ marginBottom: "1rem" }}>
              {pillars.map((p) => (
                <span className="org-chip" key={p.id}>
                  {p.name}
                  <button
                    className="btn btn-ghost"
                    style={{ padding: "0 0.4rem", marginLeft: "0.4rem", fontSize: "0.75rem" }}
                    onClick={() => handleDeletePillar(p.id)}
                    aria-label={`Delete pillar ${p.name}`}
                  >
                    ×
                  </button>
                </span>
              ))}
              {pillars.length === 0 && <span style={{ color: "var(--text-muted)" }}>No pillars yet.</span>}
            </div>
            <form onSubmit={handleAddPillar} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <input
                placeholder="Pillar name (e.g. AI Tools)"
                value={pillarName}
                onChange={(e) => setPillarName(e.target.value)}
                style={{
                  padding: "0.5rem 0.75rem", borderRadius: 8, border: "1px solid var(--border)",
                  background: "var(--bg)", color: "var(--text)",
                }}
              />
              <input
                placeholder="Description (optional)"
                value={pillarDescription}
                onChange={(e) => setPillarDescription(e.target.value)}
                style={{
                  padding: "0.5rem 0.75rem", borderRadius: 8, border: "1px solid var(--border)",
                  background: "var(--bg)", color: "var(--text)", flex: 1, minWidth: "200px",
                }}
              />
              <button type="submit" className="btn btn-primary">
                Add Pillar
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
