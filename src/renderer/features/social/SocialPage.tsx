import { useState, useRef } from "react";
import { useToast } from "../../contexts/toast";
import { apiFetch, parseJSON, authH, API } from "../../utils/api";
import { MD_COMPONENTS } from "../../shared/ui/md-components";
import { S, C } from "../../styles/theme";
import ReactMarkdown from "react-markdown";

type SocialTab = "youtube" | "facebook";
type YTInfo = { title: string; channel: string; duration: number; view_count: number; like_count: number; description: string; thumbnail: string; upload_date: string };
type SocialVariation = { text: string; hashtags?: string[]; tip?: string };

function Select({ value, onChange, opts }: { value: string; onChange: (v: string) => void; opts: [string, string][] }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} style={{ ...S.textInput, cursor: "pointer" }}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

export function SocialPage() {
  const toast = useToast();
  const [tab, setTab] = useState<SocialTab>("youtube");
  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>🌐 Social Media</span>
        <div style={{ display: "flex", gap: 4, background: "rgba(255,255,255,.04)", borderRadius: 12, padding: 4 }}>
          {([["youtube","▶ YouTube"],["facebook","📘 Social"]] as [SocialTab,string][]).map(([id,label]) => (
            <button key={id} onClick={() => setTab(id)}
              style={{ padding: "7px 18px", borderRadius: 9, border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500, transition: "all .18s",
                background: tab === id ? "linear-gradient(135deg,#D4AF37,#FFD700)" : "transparent",
                color: tab === id ? "#fff" : "rgba(148,163,184,.6)",
                boxShadow: tab === id ? "0 2px 12px rgba(255,215,0,.35)" : "none" }}>
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
      setInfo(await parseJSON<YTInfo>(r, "/api/youtube/info")); toast("Video info loaded");
    } catch (e) { toast((e as Error).message, "err"); }
    finally { setLoading(false); }
  }

  async function fetchTranscript() {
    if (!url.trim()) return;
    setTL(true); setTranscript("");
    try {
      const r = await apiFetch("/api/youtube/transcript", { method: "POST", headers: authH(), body: JSON.stringify({ url }) });
      const d = await parseJSON<{ transcript: string; language: string }>(r, "/api/youtube/transcript");
      setTranscript(d.transcript); toast(`Transcript loaded (${d.language})`);
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
      if (!res.ok || !res.body) { toast(`Error ${res.status}`, "err"); return; }
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

  const quickQ = ["لخّص هذا الفيديو", "ما أهم النقاط؟", "ما رأيك في المحتوى؟", "Summarize in English"];
  const fmtDur = (s: number) => `${Math.floor(s/60)}:${String(s%60).padStart(2,"0")}`;
  const fmtNum = (n: number) => n >= 1e6 ? `${(n/1e6).toFixed(1)}M` : n >= 1e3 ? `${(n/1e3).toFixed(1)}K` : String(n);

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Left panel */}
      <div style={{ width: 340, borderRight: "1px solid rgba(255,255,255,.05)", display: "flex", flexDirection: "column", background: "rgba(8,10,20,.6)", flexShrink: 0 }}>
        <div style={{ padding: 16, borderBottom: "1px solid rgba(255,255,255,.05)" }}>
          <div style={{ fontSize: 12, color: "rgba(148,163,184,.5)", marginBottom: 8, fontWeight: 500 }}>رابط الفيديو</div>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={url} onChange={e => setUrl(e.target.value)}
              onKeyDown={e => e.key === "Enter" && fetchInfo()}
              placeholder="https://youtube.com/watch?v=..." style={{ ...S.textInput, flex: 1, fontSize: 12 }} />
            <button onClick={fetchInfo} disabled={loading || !url.trim()} style={{ ...S.btnPrimary, padding: "0 14px", flexShrink: 0 }}>
              {loading ? "…" : "→"}
            </button>
          </div>
        </div>

        {info && (
          <div style={{ padding: 16, borderBottom: "1px solid rgba(255,255,255,.05)", overflowY: "auto" }}>
            {info.thumbnail && (
              <div style={{ borderRadius: 12, overflow: "hidden", marginBottom: 12, position: "relative" }}>
                <img src={info.thumbnail} alt="" style={{ width: "100%", display: "block", aspectRatio: "16/9", objectFit: "cover" }} />
                <div style={{ position: "absolute", bottom: 8, right: 8, background: "rgba(0,0,0,.8)", color: "#fff", fontSize: 11, padding: "2px 7px", borderRadius: 5, fontFamily: "monospace" }}>
                  {fmtDur(info.duration)}
                </div>
              </div>
            )}
            <div style={{ fontSize: 14, fontWeight: 600, color: "#f1f5f9", lineHeight: 1.4, marginBottom: 6 }}>{info.title}</div>
            <div style={{ fontSize: 12, color: "rgba(148,163,184,.6)", marginBottom: 10 }}>{info.channel}</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              {[["👁", fmtNum(info.view_count), "مشاهدة"], ["👍", fmtNum(info.like_count || 0), "إعجاب"]].map(([icon,val,label]) => (
                <div key={label} style={{ background: "rgba(255,255,255,.05)", borderRadius: 8, padding: "5px 10px", fontSize: 12, color: "#e2e8f0", display: "flex", gap: 4, alignItems: "center" }}>
                  {icon} {val} <span style={{ color: "rgba(148,163,184,.4)" }}>{label}</span>
                </div>
              ))}
            </div>
            {info.description && <div style={{ fontSize: 12, color: "rgba(148,163,184,.5)", lineHeight: 1.6 }}>{info.description}</div>}
            <button onClick={fetchTranscript} disabled={transcriptLoading}
              style={{ ...S.btnSecondary, width: "100%", marginTop: 12, fontSize: 12 }}>
              {transcriptLoading ? "⏳ جاري استخراج النص…" : transcript ? "✅ النص مُحمَّل" : "📄 استخرج النص"}
            </button>
          </div>
        )}

        {info && (
          <div style={{ padding: 12 }}>
            <div style={{ fontSize: 11, color: "rgba(148,163,184,.4)", marginBottom: 8, fontWeight: 600 }}>أسئلة سريعة</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {quickQ.map(q => (
                <button key={q} onClick={() => askQuestion(q)}
                  style={{ ...S.btnSecondary, fontSize: 12, textAlign: "left", padding: "8px 12px", borderRadius: 8 }}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Right panel — chat */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {!info ? (
          <div style={{ margin: "auto", textAlign: "center", color: "rgba(148,163,184,.3)" }}>
            <div style={{ fontSize: 64, marginBottom: 16 }}>▶</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: "rgba(148,163,184,.5)", marginBottom: 8 }}>YouTube Analyzer</div>
            <div style={{ fontSize: 14 }}>الصق رابط فيديو وابدأ التحليل بالذكاء الاصطناعي</div>
          </div>
        ) : (
          <>
            <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px", display: "flex", flexDirection: "column", gap: 16 }}>
              {!answer && !answering && (
                <div style={{ textAlign: "center", color: "rgba(148,163,184,.3)", padding: "40px 0" }}>
                  <div style={{ fontSize: 32, marginBottom: 10 }}>💬</div>
                  <div>اسأل Claude عن محتوى الفيديو</div>
                </div>
              )}
              {(answer || answering) && (
                <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                  <div style={S.avatar}><span style={{ fontSize: 18 }}>◈</span></div>
                  <div>
                    <div style={S.msgLabelAssist}>Claude</div>
                    {answering && !answer ? (
                      <div className="typing"><span /><span /><span /></div>
                    ) : (
                      <div style={{ fontSize: 15, color: "#e2e8f0", lineHeight: 1.8 }} className="md-body">
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
                placeholder="اسأل عن الفيديو…"
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
    setGen(true); setVars([]); setStatus("Connecting…");
    try {
      const res = await fetch(`${API}/api/social/generate/stream`, {
        method: "POST", headers: authH(),
        body: JSON.stringify({ topic, platform, content_type: contentType, tone, language, include_hashtags: hashtags, include_emoji: emoji, variations: 3 }),
      });
      if (!res.ok || !res.body) { toast(`Error ${res.status}`, "err"); return; }
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
            else if (ev.type === "done")      { setStatus(""); toast(`تم توليد ${ev.count} نسخ`); }
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
    toast("تم النسخ");
  }

  const platformIcon: Record<string,string> = { facebook:"📘", instagram:"📸", twitter:"🐦", linkedin:"💼" };
  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Settings panel */}
      <div style={{ width: 300, borderRight: "1px solid rgba(255,255,255,.05)", overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 16, background: "rgba(8,10,20,.6)", flexShrink: 0 }}>
        <div>
          <label style={S.label}>المنصة</label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {(["facebook","instagram","twitter","linkedin"] as const).map(p => (
              <button key={p} onClick={() => setPlatform(p)}
                style={{ padding: "9px 6px", borderRadius: 10, border: "none", cursor: "pointer", fontSize: 13, fontWeight: 500, transition: "all .18s",
                  background: platform === p ? "linear-gradient(135deg,#D4AF37,#FFD700)" : "rgba(255,255,255,.05)",
                  color: platform === p ? "#fff" : "rgba(148,163,184,.6)",
                  boxShadow: platform === p ? "0 2px 12px rgba(255,215,0,.3)" : "none" }}>
                {platformIcon[p]} {p.charAt(0).toUpperCase()+p.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label style={S.label}>نوع المحتوى</label>
          <Select value={contentType} onChange={setCType} opts={[["post","منشور عادي"],["ad","إعلان مدفوع"],["story","ستوري"],["reel_caption","كابشن ريلز"],["thread","ثريد"]]} />
        </div>
        <div>
          <label style={S.label}>الأسلوب</label>
          <Select value={tone} onChange={setTone} opts={[["engaging","جذاب وتفاعلي"],["professional","احترافي ورسمي"],["funny","مرح وفكاهي"],["inspirational","ملهم وتحفيزي"],["urgent","عاجل ومُلحّ"]]} />
        </div>
        <div>
          <label style={S.label}>اللغة</label>
          <Select value={language} onChange={setLanguage} opts={[["arabic","عربي"],["english","English"],["both","عربي + English"]]} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <label style={{ ...S.label, marginBottom: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={hashtags} onChange={e => setHashtags(e.target.checked)} /> هاشتاقات
          </label>
          <label style={{ ...S.label, marginBottom: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={emoji} onChange={e => setEmoji(e.target.checked)} /> إيموجي
          </label>
        </div>
        <div>
          <label style={S.label}>الموضوع / المنتج / الفكرة *</label>
          <textarea value={topic} onChange={e => setTopic(e.target.value)}
            placeholder={"مثال: متجر إلكتروني يبيع عطوراً فاخرة، عرض خصم 30%"}
            style={{ ...S.textInput, minHeight: 100, lineHeight: 1.6 }} />
        </div>
        <button onClick={generate} disabled={generating || !topic.trim()} style={{ ...S.btnPrimary, width: "100%", padding: "12px" }}>
          {generating ? "⏳ جاري التوليد…" : "✨ ولّد المحتوى"}
        </button>
        {status && <div style={{ fontSize: 12, color: C.purple, textAlign: "center" }}>{status}</div>}
      </div>

      {/* Results panel */}
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
        {variations.length === 0 && !generating && (
          <div style={{ margin: "auto", textAlign: "center", color: "rgba(148,163,184,.3)" }}>
            <div style={{ fontSize: 56, marginBottom: 14 }}>{platformIcon[platform]}</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: "rgba(148,163,184,.5)", marginBottom: 8 }}>
              منشئ محتوى السوشيال ميديا
            </div>
            <div style={{ fontSize: 14, maxWidth: 340, lineHeight: 1.7 }}>
              أدخل موضوعك في الإعدادات واضغط "ولّد المحتوى" للحصول على 3 نسخ احترافية
            </div>
          </div>
        )}
        {variations.map((v, i) => (
          <div key={i} style={{ ...S.card, display: "flex", flexDirection: "column", gap: 14, animation: "slideIn .25s ease" }} className="card-hover">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 28, height: 28, borderRadius: 8, background: "linear-gradient(135deg,#D4AF37,#FFD700)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, color: "#fff" }}>{i + 1}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: "#f1f5f9" }}>النسخة {i + 1}</span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={() => copy(v.text + (v.hashtags?.length ? "\n\n" + v.hashtags.join(" ") : ""), i)}
                  style={{ ...S.btnSecondary, fontSize: 12, padding: "5px 12px" }}>
                  {copied === i ? "✅ تم النسخ" : "📋 نسخ"}
                </button>
              </div>
            </div>
            <div style={{ fontSize: 15, color: "#e2e8f0", lineHeight: 1.85, whiteSpace: "pre-wrap", direction: language === "english" ? "ltr" : "rtl", textAlign: language === "english" ? "left" : "right" }}>
              {v.text}
            </div>
            {v.hashtags && v.hashtags.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {v.hashtags.map((h: string) => (
                  <span key={h} style={{ background: "rgba(255,215,0,.15)", border: "1px solid rgba(255,215,0,.25)", borderRadius: 20, padding: "3px 10px", fontSize: 12, color: "#c4b5fd" }}>
                    {h.startsWith("#") ? h : `#${h}`}
                  </span>
                ))}
              </div>
            )}
            {v.tip && (
              <div style={{ fontSize: 12, color: "rgba(148,163,184,.5)", borderTop: "1px solid rgba(255,255,255,.05)", paddingTop: 10, fontStyle: "italic" }}>
                💡 {v.tip}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
