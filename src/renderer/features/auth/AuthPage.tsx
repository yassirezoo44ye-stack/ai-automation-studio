import { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import AxonLogo from "../../AxonLogo";
import { parseJSON } from "../../utils/api";

type Tab = "login" | "register" | "forgot";

const API = import.meta.env.VITE_API_URL ?? "";

const S = {
  wrap: {
    display: "flex", alignItems: "center", justifyContent: "center",
    minHeight: "100vh",
    background: "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(139,92,246,0.12) 0%, var(--bg-base) 70%)",
    fontFamily: "var(--font-sans)",
    padding: "24px",
  } as React.CSSProperties,
  card: {
    background: "var(--bg-elevated)", border: "1px solid var(--b1)",
    borderRadius: 20, padding: "40px 36px", width: "100%", maxWidth: 420,
    boxShadow: "0 24px 64px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.04)",
  } as React.CSSProperties,
  logo: { display: "flex", justifyContent: "center", marginBottom: 12 } as React.CSSProperties,
  title: { margin: "0 0 4px", fontSize: 22, fontWeight: 700, color: "var(--t1)", textAlign: "center" } as React.CSSProperties,
  sub: { margin: "0 0 24px", fontSize: 13, color: "var(--t3)", textAlign: "center" } as React.CSSProperties,
  tabs: { display: "flex", gap: 4, marginBottom: 24, background: "var(--bg-hover)", borderRadius: 10, padding: 4 } as React.CSSProperties,
  tab: (active: boolean): React.CSSProperties => ({
    flex: 1, padding: "8px 0", borderRadius: 8, border: "none", cursor: "pointer",
    fontSize: 13, fontWeight: 600, transition: "all .15s",
    background: active ? "var(--accent)" : "transparent",
    color: active ? "#fff" : "var(--t3)",
  }),
  field: { marginBottom: 14 } as React.CSSProperties,
  label: { display: "block", fontSize: 12, color: "var(--t3)", marginBottom: 4, fontWeight: 500 } as React.CSSProperties,
  input: {
    width: "100%", padding: "10px 12px", borderRadius: 8, border: "1px solid var(--b1)",
    background: "var(--bg-input)", color: "var(--t1)", fontSize: 14,
    boxSizing: "border-box" as const, outline: "none",
  } as React.CSSProperties,
  btn: (loading: boolean): React.CSSProperties => ({
    width: "100%", padding: "11px", borderRadius: 10, border: "none",
    background: loading ? "var(--bg-card-h)" : "linear-gradient(135deg, var(--accent-light), var(--accent))",
    color: loading ? "var(--t4)" : "#fff",
    fontSize: 15, fontWeight: 700, cursor: loading ? "not-allowed" : "pointer",
    marginTop: 4, boxShadow: loading ? "none" : "var(--shadow-btn)",
    transition: "filter 0.15s, box-shadow 0.15s",
  }),
  btnSecondary: {
    width: "100%", padding: "10px", borderRadius: 10, marginTop: 8,
    border: "1px solid var(--b1)", background: "transparent",
    color: "var(--t3)", fontSize: 13, cursor: "pointer",
  } as React.CSSProperties,
  error: { color: "#f87171", fontSize: 13, margin: "0 0 12px", textAlign: "center" } as React.CSSProperties,
  success: { color: "#34d399", fontSize: 13, margin: "0 0 12px", textAlign: "center" } as React.CSSProperties,
  row: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 } as React.CSSProperties,
  check: { display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--t3)", cursor: "pointer" } as React.CSSProperties,
  link: { fontSize: 13, color: "var(--accent)", background: "none", border: "none", cursor: "pointer", padding: 0 } as React.CSSProperties,
};

export function AuthPage() {
  const { login, register } = useAuth();
  const [tab, setTab] = useState<Tab>("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Login
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPw, setLoginPw] = useState("");
  const [remember, setRemember] = useState(false);

  // Register
  const [regName, setRegName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPw, setRegPw] = useState("");
  const [regPw2, setRegPw2] = useState("");

  // Forgot
  const [forgotEmail, setForgotEmail] = useState("");

  function clear() { setError(""); setSuccess(""); }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    clear();
    setLoading(true);
    try {
      await login(loginEmail, loginPw, remember);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    clear();
    if (regPw !== regPw2) { setError("Passwords do not match"); return; }
    setLoading(true);
    try {
      const res = await register(regName, regEmail, regPw);
      setSuccess(res.message);
      setTab("login");
      setLoginEmail(regEmail);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleForgot(e: React.FormEvent) {
    e.preventDefault();
    clear();
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: forgotEmail }),
      });
      const data = await parseJSON<{ message: string }>(res, "/api/auth/forgot-password");
      setSuccess(data.message);
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={S.wrap}>
      <div style={S.card}>
        <div style={S.logo}><AxonLogo size={56} /></div>
        <h1 style={S.title}>Axon</h1>
        <p style={S.sub}>AI Automation Platform</p>

        {tab !== "forgot" && (
          <div style={S.tabs}>
            <button style={S.tab(tab === "login")} onClick={() => { setTab("login"); clear(); }}>Sign In</button>
            <button style={S.tab(tab === "register")} onClick={() => { setTab("register"); clear(); }}>Create Account</button>
          </div>
        )}

        {error && <p style={S.error}>{error}</p>}
        {success && <p style={S.success}>{success}</p>}

        {tab === "login" && (
          <form onSubmit={handleLogin}>
            <div style={S.field}>
              <label style={S.label}>Email</label>
              <input style={S.input} type="email" value={loginEmail} onChange={e => setLoginEmail(e.target.value)} required autoFocus autoComplete="email" />
            </div>
            <div style={S.field}>
              <label style={S.label}>Password</label>
              <input style={S.input} type="password" value={loginPw} onChange={e => setLoginPw(e.target.value)} required autoComplete="current-password" />
            </div>
            <div style={S.row}>
              <label style={S.check}>
                <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
                Remember me
              </label>
              <button type="button" style={S.link} onClick={() => { setTab("forgot"); clear(); setForgotEmail(loginEmail); }}>
                Forgot password?
              </button>
            </div>
            <button type="submit" style={S.btn(loading)} disabled={loading}>
              {loading ? "Signing in…" : "Sign In"}
            </button>
          </form>
        )}

        {tab === "register" && (
          <form onSubmit={handleRegister}>
            <div style={S.field}>
              <label style={S.label}>Name</label>
              <input style={S.input} type="text" value={regName} onChange={e => setRegName(e.target.value)} required autoFocus autoComplete="name" />
            </div>
            <div style={S.field}>
              <label style={S.label}>Email</label>
              <input style={S.input} type="email" value={regEmail} onChange={e => setRegEmail(e.target.value)} required autoComplete="email" />
            </div>
            <div style={S.field}>
              <label style={S.label}>Password</label>
              <input style={S.input} type="password" value={regPw} onChange={e => setRegPw(e.target.value)} required minLength={8} autoComplete="new-password" placeholder="Min 8 characters" />
            </div>
            <div style={S.field}>
              <label style={S.label}>Confirm Password</label>
              <input style={S.input} type="password" value={regPw2} onChange={e => setRegPw2(e.target.value)} required autoComplete="new-password" />
            </div>
            <button type="submit" style={S.btn(loading)} disabled={loading}>
              {loading ? "Creating account…" : "Create Account"}
            </button>
          </form>
        )}

        {tab === "forgot" && (
          <form onSubmit={handleForgot}>
            <p style={{ color: "var(--t2)", fontSize: 13, margin: "0 0 16px" }}>
              Enter your email and we'll send a password reset link.
            </p>
            <div style={S.field}>
              <label style={S.label}>Email</label>
              <input style={S.input} type="email" value={forgotEmail} onChange={e => setForgotEmail(e.target.value)} required autoFocus autoComplete="email" />
            </div>
            <button type="submit" style={S.btn(loading)} disabled={loading}>
              {loading ? "Sending…" : "Send Reset Link"}
            </button>
            <button type="button" style={S.btnSecondary} onClick={() => { setTab("login"); clear(); }}>
              Back to Sign In
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
