import { useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useToast } from "../../contexts/toast";
import { apiFetch, parseJSON, authH, API } from "../../utils/api";
import { MD_COMPONENTS } from "../../shared/ui/md-components";
import { S } from "../../styles/theme";
import { GoldButton, GlassCard } from "../../shared/ui/gold";
import ReactMarkdown from "react-markdown";

type SocialTab = "youtube" | "facebook";
type YTInfo = { title: string; channel: string; duration: number; view_count: number; like_count: number; description: string; thumbnail: string; upload_date: string };
type SocialVariation = { text: string; hashtags?: string[]; tip?: string };

function Select({ value, onChange, opts, ariaLabel }: { value: string; onChange: (v: string) => void; opts: [string, string][]; ariaLabel?: string }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} className="g-input" style={{ cursor: "pointer" }} aria-label={ariaLabel}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

export function SocialPage() {
  const { t } = useTranslation("social");
  const toast = useToast();
  const [tab, setTab] = useState<SocialTab>("youtube");
  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>🌐 {t("header")}</span>
        <div className="pill-tabs">
          {([["youtube",`▶ ${t("tabs.youtube")}`],["facebook",`📘 ${t("tabs.facebook")}`]] as [SocialTab,string][]).map(([id,label]) => (
            <button key={id} onClick={() => setTab(id)} className={`pill-tab${tab === id ? " active" : ""}`}>
              {label}
            </button>
          ))}
        </div>
      </header>
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {tab === "youtube"  && <YouTubePage toast={toast} />}
        {tab === "facebook" && <FacebookPage toast={toast} />}
      </div>
    </>
  );
}

function YouTubePage({ toast }: { toast: (m: string, k?: "ok"|"err"|"info") => void }) {
  const { t } = useTranslation("social");
  const [url, setUrl]               = useState("");
  const [loading, setLoading]       = useState(false);
  const [info, setInfo]             = useState<YTInfo | null>(null);
  const [transcript, setTranscript] = useState("");
  const [transcriptLoading, setTL]  = useState(false);
  const [question, setQuestion]     = useState("");
  const [answer, setAnswer]         = useState("");
  const [answering, setAnswering]   = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function fetchInfo() {
    if (!url.trim()) return;
    setLoading(true); setInfo(null); setTranscript(""); setAnswer("");
    try {
      const r = await apiFetch("/api/youtube/info", { method: "POST", headers: authH(), body: JSON.stringify({ url }) });
      setInfo(await parseJSON<YTInfo>(r, "/api/youtube/info")); toast(t("youtube.infoLoaded"));
    } catch (e) { toast((e as Error).message, "err"); }
    finally { setLoading(false); }
  }

  async function fetchTranscript() {
    if (!url.trim()) return;
    setTL(true); setTranscript("");
    try {
      const r = await apiFetch("/api/youtube/transcript", { method: "POST", headers: authH(), body: JSON.stringify({ url }) });
      const d = await parseJSON<{ transcript: string; language: string }>(r, "/api/youtube/transcript");
      setTranscript(d.transcript); toast(t("youtube.transcriptLoadedWithLang", { language: d.language }));
    } catch (e) { toast((e as Error).message, "err"); }
    finally { setTL(false); }
  }

  async function askQuestion(q?: string) {
    const finalQ = q ?? question.trim();
    if (!finalQ) return;
    setQuestion(finalQ); setAnswer(""); setAnswering(true);
    const ctrl = new AbortController(); abortRef.current = ctrl;
    try {
      const res = await fetch(`${API}/api/youtube/analyze/stream`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({ url, question: finalQ, transcript }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) { toast(t("youtube.errorStatus", { status: res.status }), "err"); return; }
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "delta") setAnswer(p => p + ev.text);
            else if (ev.type === "error") { toast(ev.message, "err"); break; }
          } catch {}
        }
      }
    } catch (e) { if ((e as Error).name !== "AbortError") toast((e as Error).message, "err"); }
    finally { setAnswering(false); }
  }

  const quickQ = [t("youtube.q1"), t("youtube.q2"), t("youtube.q3"), t("youtube.q4")];
  const fmtDur = (s: number) => `${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`;
  const fmtNum = (n: number) => n >= 1e6 ? `${(n/1e6).toFixed(1)}M` : n >= 1e3 ? `${(n/1e3).toFixed(1)}K` : String(n);

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Left panel */}
      <div style={{ width: 340, borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", background: "var(--bg-panel)", flexShrink: 0 }}>
        <div style={{ padding: 16, borderBottom: "1px solid var(--border)" }}>
          <div style={{ fontSize: 12, color: "var(--t4)", marginBottom: 8, fontWeight: 500 }}>{t("youtube.videoLink")}</div>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={url} onChange={e => setUrl(e.target.value)}
              onKeyDown={e => e.key === "Enter" && fetchInfo()}
              placeholder="https://youtube.com/watch?v=..." className="g-input" style={{ flex: 1, fontSize: 12 }} />
            <GoldButton onClick={fetchInfo} disabled={loading || !url.trim()} style={{ padding: "0 14px", flexShrink: 0 }}>
              {loading ? "…" : "→"}
            </GoldButton>
          </div>
        </div>

        {info && (
          <div style={{ padding: 16, borderBottom: "1px solid var(--border)", overflowY: "auto" }}>
            {info.thumbnail && (
              <div style={{ borderRadius: 12, overflow: "hidden", marginBottom: 12, position: "relative" }}>
                <img src={info.thumbnail} alt="" style={{ width: "100%", display: "block", aspectRatio: "16/9", objectFit: "cover" }} />
                {/* Overlay on arbitrary thumbnail imagery — stays fixed black/white
                    regardless of app theme, same as the AI Routing theme-swatch
                    previews, since it must read against unpredictable photo content. */}
                <div style={{ position: "absolute", bottom: 8, right: 8, background: "rgba(0,0,0,.8)", color: "#fff", fontSize: 11, padding: "2px 7px", borderRadius: 5, fontFamily: "var(--font-mono)" }}>
                  {fmtDur(info.duration)}
                </div>
              </div>
            )}
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", lineHeight: 1.4, marginBottom: 6 }}>{info.title}</div>
            <div style={{ fontSize: 12, color: "var(--t3)", marginBottom: 10 }}>{info.channel}</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              {[["👁", fmtNum(info.view_count), t("youtube.views")], ["👍", fmtNum(info.like_count || 0), t("youtube.likes")]].map(([icon,val,label]) => (
                <div key={label} style={{ background: "var(--bg-hover)", borderRadius: 8, padding: "5px 10px", fontSize: 12, color: "var(--t2)", display: "flex", gap: 4, alignItems: "center" }}>
                  {icon} {val} <span style={{ color: "var(--t4)" }}>{label}</span>
                </div>
              ))}
            </div>
            {info.description && <div style={{ fontSize: 12, color: "var(--t4)", lineHeight: 1.6 }}>{info.description}</div>}
            <GoldButton variant="ghost" onClick={fetchTranscript} disabled={transcriptLoading} style={{ width: "100%", marginTop: 12, fontSize: 12 }}>
              {transcriptLoading ? `⏳ ${t("youtube.extracting")}` : transcript ? `✅ ${t("youtube.transcriptLoaded")}` : `📄 ${t("youtube.extractTranscript")}`}
            </GoldButton>
          </div>
        )}

        {info && (
          <div style={{ padding: 12 }}>
            <div style={{ fontSize: 11, color: "var(--t5)", marginBottom: 8, fontWeight: 600 }}>{t("youtube.quickQuestions")}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {quickQ.map(q => (
                <GoldButton key={q} variant="ghost" onClick={() => askQuestion(q)} style={{ fontSize: 12, textAlign: "left" as const, padding: "8px 12px" }}>
                  {q}
                </GoldButton>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Right panel — chat */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {!info ? (
          <div style={{ margin: "auto", textAlign: "center", color: "var(--t5)" }}>
            <div style={{ fontSize: 64, marginBottom: 16 }}>▶</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: "var(--t4)", marginBottom: 8 }}>{t("youtube.emptyTitle")}</div>
            <div style={{ fontSize: 14 }}>{t("youtube.emptyDesc")}</div>
          </div>
        ) : (
          <>
            <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px", display: "flex", flexDirection: "column", gap: 16 }}>
              {!answer && !answering && (
                <div style={{ textAlign: "center", color: "var(--t5)", padding: "40px 0" }}>
                  <div style={{ fontSize: 32, marginBottom: 10 }}>💬</div>
                  <div>{t("youtube.askPrompt")}</div>
                </div>
              )}
              {(answer || answering) && (
                <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                  {/* S.avatar/msgLabelAssist are the shared AI-chat bubble styles
                      (still hardcoded, not yet token-based) — deferred to the
                      AI Workspace page's own migration turn, which owns this
                      exact chat UI primarily; not touched here to keep this
                      page's diff scoped to SocialPage.tsx. */}
                  <div style={S.avatar}><span style={{ fontSize: 18 }}>◈</span></div>
                  <div>
                    <div style={S.msgLabelAssist}>Claude</div>
                    {answering && !answer ? (
                      <div className="typing"><span /><span /><span /></div>
                    ) : (
                      <div style={{ fontSize: 15, color: "var(--t2)", lineHeight: 1.8 }} className="md-body">
                        <ReactMarkdown components={MD_COMPONENTS}>{answer}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
            <div style={S.inputRow}>
              <input value={question} onChange={e => setQuestion(e.target.value)}
                onKeyDown={e => e.key === "Enter" && askQuestion()}
                placeholder={t("youtube.inputPlaceholder")}
                style={{ ...S.input, borderRadius: 12, padding: "12px 16px" }} />
              <button onClick={() => askQuestion()} disabled={answering || !question.trim()} style={S.sendBtn}>↑</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function FacebookPage({ toast }: { toast: (m: string, k?: "ok"|"err"|"info") => void }) {
  const { t } = useTranslation("social");
  const [topic, setTopic]       = useState("");
  const [platform, setPlatform] = useState("facebook");
  const [contentType, setCType] = useState("post");
  const [tone, setTone]         = useState("engaging");
  const [language, setLanguage] = useState("arabic");
  const [hashtags, setHashtags] = useState(true);
  const [emoji, setEmoji]       = useState(true);
  const [variations, setVars]   = useState<SocialVariation[]>([]);
  const [generating, setGen]    = useState(false);
  const [status, setStatus]     = useState("");
  const [copied, setCopied]     = useState<number | null>(null);

  async function generate() {
    if (!topic.trim()) return;
    setGen(true); setVars([]); setStatus(t("facebook.connecting"));
    try {
      const res = await fetch(`${API}/api/social/generate/stream`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({ topic, platform, content_type: contentType, tone, language, include_hashtags: hashtags, include_emoji: emoji, variations: 3 }),
      });
      if (!res.ok || !res.body) { toast(t("facebook.errorStatus", { status: res.status }), "err"); return; }
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "status")         setStatus(ev.message);
            else if (ev.type === "variation") setVars(p => [...p, ev.data]);
            else if (ev.type === "done")      { setStatus(""); toast(t("facebook.generatedCount", { count: ev.count })); }
            else if (ev.type === "error")     { setStatus(""); toast(ev.message, "err"); }
          } catch {}
        }
      }
    } catch (e) { toast((e as Error).message, "err"); setStatus(""); }
    finally { setGen(false); }
  }

  function copy(text: string, i: number) {
    navigator.clipboard.writeText(text);
    setCopied(i); setTimeout(() => setCopied(null), 2000);
    toast(t("facebook.copied"));
  }

  const platformIcon: Record<string,string> = { facebook:"📘", instagram:"📸", twitter:"🐦", linkedin:"💼" };
  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Settings panel */}
      <div style={{ width: 300, borderRight: "1px solid var(--border)", overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 16, background: "var(--bg-panel)", flexShrink: 0 }}>
        <div>
          <div className="g-label">{t("facebook.platform")}</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {(["facebook","instagram","twitter","linkedin"] as const).map(p => (
              <button key={p} onClick={() => setPlatform(p)} className={`pill-tab${platform === p ? " active" : ""}`}>
                {platformIcon[p]} {p.charAt(0).toUpperCase()+p.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="g-label">{t("facebook.contentType")}</div>
          <Select value={contentType} onChange={setCType} ariaLabel={t("facebook.contentType")} opts={[["post",t("facebook.contentTypeOptions.post")],["ad",t("facebook.contentTypeOptions.ad")],["story",t("facebook.contentTypeOptions.story")],["reel_caption",t("facebook.contentTypeOptions.reelCaption")],["thread",t("facebook.contentTypeOptions.thread")]]} />
        </div>
        <div>
          <div className="g-label">{t("facebook.tone")}</div>
          <Select value={tone} onChange={setTone} ariaLabel={t("facebook.tone")} opts={[["engaging",t("facebook.toneOptions.engaging")],["professional",t("facebook.toneOptions.professional")],["funny",t("facebook.toneOptions.funny")],["inspirational",t("facebook.toneOptions.inspirational")],["urgent",t("facebook.toneOptions.urgent")]]} />
        </div>
        <div>
          <div className="g-label">{t("facebook.language")}</div>
          <Select value={language} onChange={setLanguage} ariaLabel={t("facebook.language")} opts={[["arabic",t("facebook.languageOptions.arabic")],["english",t("facebook.languageOptions.english")],["both",t("facebook.languageOptions.both")]]} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <label className="g-label" style={{ marginBottom: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={hashtags} onChange={e => setHashtags(e.target.checked)} /> {t("facebook.hashtags")}
          </label>
          <label className="g-label" style={{ marginBottom: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={emoji} onChange={e => setEmoji(e.target.checked)} /> {t("facebook.emoji")}
          </label>
        </div>
        <div>
          <div className="g-label">{t("facebook.topic")}</div>
          <textarea value={topic} onChange={e => setTopic(e.target.value)}
            placeholder={t("facebook.topicPlaceholder")}
            className="g-input" style={{ minHeight: 100, lineHeight: 1.6 }}
            aria-label={t("facebook.topic")} />
        </div>
        <GoldButton onClick={generate} disabled={generating || !topic.trim()} style={{ width: "100%", padding: "12px" }}>
          {generating ? `⏳ ${t("facebook.generating")}` : `✨ ${t("facebook.generate")}`}
        </GoldButton>
        {status && <div style={{ fontSize: 12, color: "var(--accent)", textAlign: "center" }}>{status}</div>}
      </div>

      {/* Results panel */}
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
        {variations.length === 0 && !generating && (
          <div style={{ margin: "auto", textAlign: "center", color: "var(--t5)" }}>
            <div style={{ fontSize: 56, marginBottom: 14 }}>{platformIcon[platform]}</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: "var(--t4)", marginBottom: 8 }}>
              {t("facebook.emptyTitle")}
            </div>
            <div style={{ fontSize: 14, maxWidth: 340, lineHeight: 1.7 }}>
              {t("facebook.emptyDesc")}
            </div>
          </div>
        )}
        {variations.map((v, i) => (
          <GlassCard key={i} style={{ display: "flex", flexDirection: "column", gap: 14, animation: "slideIn .25s ease" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 28, height: 28, borderRadius: 8, background: "linear-gradient(135deg, var(--accent), var(--accent-2))", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, color: "#fff" }}>{i + 1}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{t("facebook.variation", { n: i + 1 })}</span>
              </div>
              <GoldButton variant="ghost" onClick={() => copy(v.text + (v.hashtags?.length ? "\n\n" + v.hashtags.join(" ") : ""), i)} style={{ fontSize: 12, padding: "5px 12px" }}>
                {copied === i ? `✅ ${t("facebook.copiedShort")}` : `📋 ${t("facebook.copy")}`}
              </GoldButton>
            </div>
            <div style={{ fontSize: 15, color: "var(--t2)", lineHeight: 1.85, whiteSpace: "pre-wrap", direction: language === "english" ? "ltr" : "rtl", textAlign: language === "english" ? "left" : "right" }}>
              {v.text}
            </div>
            {v.hashtags && v.hashtags.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {v.hashtags.map((h: string) => (
                  <span key={h} className="badge badge-purple">
                    {h.startsWith("#") ? h : `#${h}`}
                  </span>
                ))}
              </div>
            )}
            {v.tip && (
              <div style={{ fontSize: 12, color: "var(--t4)", borderTop: "1px solid var(--border)", paddingTop: 10, fontStyle: "italic" }}>
                💡 {v.tip}
              </div>
            )}
          </GlassCard>
        ))}
      </div>
    </div>
  );
}
