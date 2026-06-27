import { useState, useRef, useEffect } from "react";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

const API = "http://127.0.0.1:8000";

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    const text = prompt.trim();
    if (!text || loading) return;
    setPrompt("");

    const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await fetch(`${API}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: "demo", prompt: text }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", content: data.result.summary },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", content: "⚠️ Could not reach the backend. Make sure `python main.py` is running on port 8000." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div style={styles.root}>
      {/* Sidebar */}
      <aside style={styles.sidebar}>
        <div style={styles.sidebarLogo}>◈ AI Studio</div>
        <nav style={styles.nav}>
          <div style={{ ...styles.navItem, ...styles.navItemActive }}>💬 Chat</div>
          <a href="/dashboard.html" style={{ ...styles.navItem, textDecoration: "none" }}>📊 Dashboard</a>
          <div style={styles.navItem}>📁 Projects</div>
          <div style={styles.navItem}>⚙️ Settings</div>
        </nav>
      </aside>

      {/* Main */}
      <main style={styles.main}>
        <header style={styles.header}>
          <span style={styles.headerTitle}>Chat with Claude</span>
          <span style={styles.headerSub}>claude-sonnet-4-6 · Demo Project</span>
        </header>

        {/* Messages */}
        <div style={styles.messages}>
          {messages.length === 0 && (
            <div style={styles.empty}>
              <div style={styles.emptyIcon}>◈</div>
              <div style={styles.emptyTitle}>AI Automation Studio</div>
              <div style={styles.emptySub}>Ask Claude anything to get started.</div>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} style={{ ...styles.bubble, ...(m.role === "user" ? styles.bubbleUser : styles.bubbleAssistant) }}>
              <div style={styles.bubbleRole}>{m.role === "user" ? "You" : "Claude"}</div>
              <div style={styles.bubbleText}>{m.content}</div>
            </div>
          ))}
          {loading && (
            <div style={{ ...styles.bubble, ...styles.bubbleAssistant }}>
              <div style={styles.bubbleRole}>Claude</div>
              <div style={styles.typing}><span /><span /><span /></div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={styles.inputRow}>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Message Claude… (Enter to send, Shift+Enter for newline)"
            style={styles.input}
            rows={1}
          />
          <button onClick={sendMessage} disabled={loading || !prompt.trim()} style={styles.sendBtn}>
            {loading ? "…" : "↑"}
          </button>
        </div>
      </main>

      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
          40% { transform: translateY(-6px); opacity: 1; }
        }
        .typing span {
          display: inline-block;
          width: 6px; height: 6px;
          background: #6c8ef7;
          border-radius: 50%;
          margin: 0 2px;
          animation: bounce 1.2s infinite;
        }
        .typing span:nth-child(2) { animation-delay: 0.2s; }
        .typing span:nth-child(3) { animation-delay: 0.4s; }
        textarea { resize: none; }
        textarea:focus { outline: none; }
        button:focus { outline: none; }
        * { box-sizing: border-box; }
        body { margin: 0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0d0f14; }
        ::-webkit-scrollbar-thumb { background: #2a3050; border-radius: 3px; }
      `}</style>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: "flex",
    height: "100vh",
    background: "#0d0f14",
    color: "#e2e8f0",
    fontFamily: "'Segoe UI', system-ui, sans-serif",
    overflow: "hidden",
  },
  sidebar: {
    width: 220,
    background: "#0a0c10",
    borderRight: "1px solid #1e2438",
    display: "flex",
    flexDirection: "column",
    padding: "20px 0",
    flexShrink: 0,
  },
  sidebarLogo: {
    fontSize: 18,
    fontWeight: 700,
    color: "#6c8ef7",
    padding: "0 20px 24px",
    borderBottom: "1px solid #1e2438",
    marginBottom: 12,
  },
  nav: { display: "flex", flexDirection: "column", gap: 4, padding: "0 12px" },
  navItem: {
    padding: "10px 12px",
    borderRadius: 8,
    fontSize: 13,
    color: "#8896b3",
    cursor: "pointer",
    transition: "background 0.15s",
  },
  navItemActive: { background: "#1a1f2e", color: "#c8d3f0" },
  main: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  header: {
    padding: "16px 24px",
    borderBottom: "1px solid #1e2438",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    background: "#0d0f14",
  },
  headerTitle: { fontSize: 15, fontWeight: 600, color: "#f0f4ff" },
  headerSub: { fontSize: 12, color: "#4b5980" },
  messages: {
    flex: 1,
    overflowY: "auto",
    padding: "24px",
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  empty: {
    margin: "auto",
    textAlign: "center",
    color: "#4b5980",
    paddingBottom: 80,
  },
  emptyIcon: { fontSize: 40, color: "#6c8ef7", marginBottom: 12 },
  emptyTitle: { fontSize: 20, fontWeight: 700, color: "#c8d3f0", marginBottom: 8 },
  emptySub: { fontSize: 14 },
  bubble: {
    maxWidth: 720,
    padding: "12px 16px",
    borderRadius: 12,
    lineHeight: 1.6,
  },
  bubbleUser: {
    alignSelf: "flex-end",
    background: "#1a2040",
    border: "1px solid #2a3458",
    borderBottomRightRadius: 3,
  },
  bubbleAssistant: {
    alignSelf: "flex-start",
    background: "#13172080",
    border: "1px solid #1e2438",
    borderBottomLeftRadius: 3,
  },
  bubbleRole: { fontSize: 11, color: "#6c8ef7", fontWeight: 600, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 },
  bubbleText: { fontSize: 14, color: "#c8d3f0", whiteSpace: "pre-wrap" },
  typing: { display: "flex", alignItems: "center", height: 20 },
  inputRow: {
    padding: "16px 24px",
    borderTop: "1px solid #1e2438",
    display: "flex",
    gap: 10,
    alignItems: "flex-end",
    background: "#0d0f14",
  },
  input: {
    flex: 1,
    background: "#13172080",
    border: "1px solid #2a3050",
    borderRadius: 10,
    padding: "12px 16px",
    color: "#e2e8f0",
    fontSize: 14,
    lineHeight: 1.5,
    maxHeight: 160,
    overflowY: "auto",
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 10,
    background: "#6c8ef7",
    color: "#fff",
    border: "none",
    fontSize: 18,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    opacity: 1,
    transition: "opacity 0.15s",
  },
};
