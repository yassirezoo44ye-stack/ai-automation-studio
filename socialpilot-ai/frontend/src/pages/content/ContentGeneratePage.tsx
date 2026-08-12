import { useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import * as contentApi from "../../api/content";
import { ApiError } from "../../api/client";
import type {
  ContentGeneration, ContentPillar, ContentStrategy, GeneratedIdea, GeneratedPost,
} from "../../api/contentTypes";
import { useCurrentOrg } from "../../hooks/useCurrentOrg";

const PLATFORMS = ["x", "linkedin", "instagram", "facebook", "tiktok", "youtube"];

export function ContentGeneratePage() {
  const org = useCurrentOrg();
  const [strategies, setStrategies] = useState<ContentStrategy[]>([]);
  const [strategyId, setStrategyId] = useState("");
  const [pillars, setPillars] = useState<ContentPillar[]>([]);
  const [pillarId, setPillarId] = useState("");
  const [platform, setPlatform] = useState("x");
  const [tone, setTone] = useState("");
  const [language, setLanguage] = useState("");
  const [brief, setBrief] = useState("");

  const [generating, setGenerating] = useState(false);
  const [generation, setGeneration] = useState<ContentGeneration | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedIndex, setSavedIndex] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!org) return;
    contentApi.listStrategies(org.id).then((list) => {
      setStrategies(list);
      if (list.length > 0) setStrategyId(list[0].id);
    });
  }, [org]);

  useEffect(() => {
    if (!org || !strategyId) {
      setPillars([]);
      return;
    }
    contentApi.listPillars(org.id, strategyId).then(setPillars).catch(() => setPillars([]));
  }, [org, strategyId]);

  if (!org) return <div className="center-loading">Loading…</div>;

  const runGeneration = async (kind: "ideas" | "post") => {
    setError(null);
    setGeneration(null);
    setSavedIndex(null);
    setGenerating(true);
    try {
      const result =
        kind === "ideas"
          ? await contentApi.generateIdeas(org.id, {
              strategy_id: strategyId,
              pillar_id: pillarId || undefined,
              platform: platform || undefined,
              tone: tone || undefined,
              language: language || undefined,
              count: 5,
            })
          : await contentApi.generatePost(org.id, {
              strategy_id: strategyId,
              pillar_id: pillarId || undefined,
              platform,
              tone: tone || undefined,
              language: language || undefined,
              brief: brief || undefined,
            });
      setGeneration(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Generation request failed");
    } finally {
      setGenerating(false);
    }
  };

  const saveIdea = async (idea: GeneratedIdea, index: number) => {
    if (!generation) return;
    setSaving(true);
    try {
      await contentApi.createItem(org.id, {
        strategy_id: strategyId,
        generation_id: generation.id,
        platform: idea.suggested_platform,
        title: idea.title,
        body: idea.concept,
        hashtags: [],
        metadata: { hook: idea.hook, cta: idea.cta, pillar: idea.pillar },
      });
      setSavedIndex(index);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save idea");
    } finally {
      setSaving(false);
    }
  };

  const savePost = async (post: GeneratedPost) => {
    if (!generation) return;
    setSaving(true);
    try {
      await contentApi.createItem(org.id, {
        strategy_id: strategyId,
        generation_id: generation.id,
        platform: post.platform,
        title: post.hook,
        body: post.body,
        hashtags: post.hashtags,
        metadata: { hook: post.hook, cta: post.cta, media_concept: post.media_concept },
      });
      setSavedIndex(0);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save post");
    } finally {
      setSaving(false);
    }
  };

  if (strategies.length === 0) {
    return (
      <div className="page">
        <div className="dashboard">
          <h1>Generate Content</h1>
          <div className="notice-card">
            You need a content strategy first. <Link to="/content/strategy">Create one</Link>.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="dashboard">
        <h1>Generate Content</h1>

        <div className="composer" style={{ textAlign: "left" }}>
          <div className="field">
            <label htmlFor="strategy-select">Strategy</label>
            <select
              id="strategy-select"
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              style={selectStyle}
            >
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="pillar-select">Content pillar (optional)</label>
            <select id="pillar-select" value={pillarId} onChange={(e) => setPillarId(e.target.value)} style={selectStyle}>
              <option value="">— none —</option>
              {pillars.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="platform-select">Platform</label>
            <select id="platform-select" value={platform} onChange={(e) => setPlatform(e.target.value)} style={selectStyle}>
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="tone-input">Tone override (optional)</label>
            <input id="tone-input" value={tone} onChange={(e) => setTone(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="language-input">Language override (optional)</label>
            <input id="language-input" value={language} onChange={(e) => setLanguage(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="brief-input">Brief for a post (optional — e.g. an idea's concept)</label>
            <input id="brief-input" value={brief} onChange={(e) => setBrief(e.target.value)} />
          </div>

          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button className="btn btn-primary" disabled={generating} onClick={() => runGeneration("ideas")}>
              {generating ? "Generating…" : "Generate Ideas"}
            </button>
            <button className="btn btn-ghost" disabled={generating} onClick={() => runGeneration("post")}>
              {generating ? "Generating…" : "Generate Post"}
            </button>
          </div>
        </div>

        {error && <div className="error-banner" style={{ marginTop: "1rem" }}>{error}</div>}

        {generation && generation.status === "failed" && (
          <div className="error-banner" style={{ marginTop: "1rem" }}>
            Generation failed: {generation.error}
          </div>
        )}

        {generation && generation.status === "succeeded" && generation.result && "ideas" in generation.result && (
          <div style={{ marginTop: "1.5rem" }}>
            <div className="section-title">Ideas</div>
            {generation.result.ideas.map((idea, i) => (
              <div className="notice-card" key={i} style={{ marginBottom: "0.75rem", textAlign: "left" }}>
                <strong>{idea.title}</strong>
                <p style={{ margin: "0.5rem 0" }}>{idea.concept}</p>
                <p style={{ margin: "0.25rem 0", color: "var(--text-muted)" }}>
                  Hook: {idea.hook} — CTA: {idea.cta} — Pillar: {idea.pillar} — Platform: {idea.suggested_platform}
                </p>
                <button
                  className="btn btn-primary"
                  disabled={saving}
                  onClick={() => saveIdea(idea, i)}
                >
                  {savedIndex === i ? "Saved ✓" : "Save to Library"}
                </button>
                <button
                  className="btn btn-ghost"
                  style={{ marginLeft: "0.5rem" }}
                  onClick={() => setBrief(idea.concept)}
                >
                  Use as post brief
                </button>
              </div>
            ))}
          </div>
        )}

        {generation && generation.status === "succeeded" && generation.result && "body" in generation.result && (
          <div style={{ marginTop: "1.5rem" }}>
            <div className="section-title">Post</div>
            <div className="notice-card" style={{ textAlign: "left" }}>
              <strong>{generation.result.hook}</strong>
              <p style={{ margin: "0.5rem 0", whiteSpace: "pre-wrap" }}>{generation.result.body}</p>
              <p style={{ margin: "0.25rem 0", color: "var(--text-muted)" }}>CTA: {generation.result.cta}</p>
              <p style={{ margin: "0.25rem 0", color: "var(--text-muted)" }}>
                Hashtags: {generation.result.hashtags.map((h) => `#${h}`).join(" ")}
              </p>
              <p style={{ margin: "0.25rem 0", color: "var(--text-muted)" }}>
                Media concept: {generation.result.media_concept}
              </p>
              <button className="btn btn-primary" disabled={saving} onClick={() => savePost(generation.result as GeneratedPost)}>
                {savedIndex === 0 ? "Saved ✓" : "Save to Library"}
              </button>
              <button className="btn btn-ghost" style={{ marginLeft: "0.5rem" }} onClick={() => runGeneration("post")}>
                Regenerate
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const selectStyle: CSSProperties = {
  width: "100%",
  padding: "0.6rem 0.75rem",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "var(--bg)",
  color: "var(--text)",
  fontSize: "0.95rem",
};
