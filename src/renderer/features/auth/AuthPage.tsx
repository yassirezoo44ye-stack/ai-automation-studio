import { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import AxonLogo from "../../AxonLogo";
import { parseJSON } from "../../utils/api";
import { useForm } from "../../shared/forms/useForm";
import { useAsyncSubmit } from "../../shared/forms/useAsyncSubmit";
import { all, required, email as emailValidator, minLength, matchesField, passwordStrength } from "../../shared/forms/validators";
import { EmailField, PasswordField, TextField, Checkbox, SubmitButton, ErrorBanner, SuccessBanner } from "../../shared/ui/forms";
import { GoldButton } from "../../shared/ui/gold";

type Tab = "login" | "register" | "forgot";

const API = import.meta.env.VITE_API_URL ?? "";

const S = {
  wrap: {
    display: "flex", alignItems: "center", justifyContent: "center",
    minHeight: "100vh",
    background: "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(255,215,0,0.12) 0%, var(--bg-base) 70%)",
    fontFamily: "var(--font-sans)",
    padding: "24px",
  } as React.CSSProperties,
  card: {
    background: "var(--bg-elevated)", border: "1px solid var(--b1)",
    borderRadius: 20, padding: "40px 36px", width: "100%", maxWidth: 420,
    boxShadow: "0 24px 64px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.04)",
  } as React.CSSProperties,
  logo:  { display: "flex", justifyContent: "center", marginBottom: 12 } as React.CSSProperties,
  title: { margin: "0 0 2px", fontSize: 22, fontWeight: 700, color: "var(--t1)", textAlign: "center" } as React.CSSProperties,
  sub:   { margin: "0 0 24px", fontSize: 13, color: "var(--t3)", textAlign: "center" } as React.CSSProperties,
  tabs:  { display: "flex", gap: 4, marginBottom: 24, background: "var(--bg-hover)", borderRadius: 10, padding: 4 } as React.CSSProperties,
  tab:   (active: boolean): React.CSSProperties => ({
    flex: 1, padding: "8px 0", borderRadius: 8, border: "none", cursor: "pointer",
    fontSize: 13, fontWeight: 600, transition: "all .15s",
    background: active ? "var(--accent)" : "transparent",
    color: active ? "#fff" : "var(--t3)",
  }),
  divider: {
    display: "flex", alignItems: "center", gap: 10,
    margin: "18px 0", color: "var(--t4)", fontSize: 12,
  } as React.CSSProperties,
  divLine: { flex: 1, height: 1, background: "var(--b1)" } as React.CSSProperties,
  oauthRow: { display: "flex", gap: 8, marginBottom: 0 } as React.CSSProperties,
  oauthBtn: (_color: string): React.CSSProperties => ({
    flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
    padding: "10px 12px", borderRadius: 10, border: "1px solid var(--b1)",
    background: "var(--bg-input)", color: "var(--t1)", fontSize: 13, fontWeight: 600,
    cursor: "pointer", transition: "background .15s",
  }),
  row:     { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 } as React.CSSProperties,
  link:    { fontSize: 13, color: "var(--accent)", background: "none", border: "none", cursor: "pointer", padding: 0 } as React.CSSProperties,
  btnSecondary: {
    width: "100%", padding: "10px", borderRadius: 10, marginTop: 8,
    border: "1px solid var(--b1)", background: "transparent",
    color: "var(--t3)", fontSize: 13, cursor: "pointer",
  } as React.CSSProperties,
  btnText: {
    width: "100%", padding: "8px", borderRadius: 8, marginTop: 6,
    border: "none", background: "transparent",
    color: "var(--accent)", fontSize: 13, cursor: "pointer", textDecoration: "underline",
  } as React.CSSProperties,
};

// ── OAuth provider buttons ────────────────────────────────────────────────────

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48">
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.5-1.45-.79-3-.79-4.59s.29-3.14.79-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
    </svg>
  );
}

function MicrosoftIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24">
      <path fill="#F25022" d="M1 1h10v10H1z"/>
      <path fill="#7FBA00" d="M13 1h10v10H13z"/>
      <path fill="#00A4EF" d="M1 13h10v10H1z"/>
      <path fill="#FFB900" d="M13 13h10v10H13z"/>
    </svg>
  );
}

function OAuthRow({ onSelect }: { onSelect: (provider: "google" | "github" | "microsoft") => void }) {
  return (
    <>
      <div style={S.oauthRow}>
        <button style={S.oauthBtn("#4285F4")} onClick={() => onSelect("google")} type="button">
          <GoogleIcon /> Google
        </button>
        <button style={S.oauthBtn("#24292e")} onClick={() => onSelect("github")} type="button">
          <GitHubIcon /> GitHub
        </button>
        <button style={S.oauthBtn("#2f2f2f")} onClick={() => onSelect("microsoft")} type="button">
          <MicrosoftIcon /> Microsoft
        </button>
      </div>
      <div style={S.divider}>
        <span style={S.divLine} /><span>or</span><span style={S.divLine} />
      </div>
    </>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface LoginValues { email: string; password: string; remember: boolean }
interface RegisterValues { name: string; email: string; password: string; confirmPassword: string }
interface ForgotValues { email: string }

export function AuthPage() {
  const { login, register } = useAuth();
  const [tab, setTab] = useState<Tab>("login");
  const [registeredEmail, setRegisteredEmail] = useState<string | null>(null);

  function handleOAuth(provider: "google" | "github" | "microsoft") {
    window.location.href = `${API}/api/auth/${provider}`;
  }

  // ── Login ──────────────────────────────────────────────────────────────────
  const loginSubmit = useAsyncSubmit<void>();
  const loginForm = useForm<LoginValues>({
    initialValues: { email: "", password: "", remember: false },
    validators: {
      email: all(required("Email is required"), emailValidator()),
      password: required("Password is required"),
    },
    onValid: values => loginSubmit.run(() => login(values.email, values.password, values.remember)),
  });

  // ── Register ───────────────────────────────────────────────────────────────
  const registerSubmit = useAsyncSubmit<{ message: string }>();
  const registerForm = useForm<RegisterValues>({
    initialValues: { name: "", email: "", password: "", confirmPassword: "" },
    validators: {
      name: required("Name is required"),
      email: all(required("Email is required"), emailValidator()),
      password: all(required("Password is required"), minLength(8), passwordStrength()),
      confirmPassword: all(required("Please confirm your password"), matchesField("password", "Passwords do not match")),
    },
    onValid: values => {
      registerSubmit.run(async () => {
        const res = await register(values.name, values.email, values.password);
        setRegisteredEmail(values.email);
        return res;
      });
    },
  });

  // ── Forgot password ────────────────────────────────────────────────────────
  const forgotSubmit = useAsyncSubmit<{ message: string }>();
  const forgotForm = useForm<ForgotValues>({
    initialValues: { email: "" },
    validators: { email: all(required("Email is required"), emailValidator()) },
    onValid: values => forgotSubmit.run(async signal => {
      const res = await fetch(`${API}/api/auth/forgot-password`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: values.email }),
        signal,
      });
      return parseJSON<{ message: string }>(res, "/api/auth/forgot-password");
    }),
  });

  // ── Resend verification (button action, no fields) ────────────────────────
  const resendSubmit = useAsyncSubmit<{ message: string }>();
  function handleResend() {
    if (!registeredEmail) return;
    resendSubmit.run(async signal => {
      const res = await fetch(`${API}/api/auth/resend-verification`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: registeredEmail }),
        signal,
      });
      return parseJSON<{ message: string }>(res, "/api/auth/resend-verification");
    });
  }

  function switchTab(next: Tab) {
    setTab(next);
    loginSubmit.reset(); registerSubmit.reset(); forgotSubmit.reset(); resendSubmit.reset();
    if (next !== "register") setRegisteredEmail(null);
  }

  return (
    <div style={S.wrap}>
      <div style={S.card}>
        <div style={S.logo}><AxonLogo size={56} /></div>
        <h1 style={S.title}>AI Automation Studio</h1>
        <p style={S.sub}>Powered by Axon AI Platform</p>

        {tab !== "forgot" && (
          <div style={S.tabs} role="tablist">
            <button role="tab" aria-selected={tab === "login"} style={S.tab(tab === "login")} onClick={() => switchTab("login")}>
              Sign In
            </button>
            <button role="tab" aria-selected={tab === "register"} style={S.tab(tab === "register")} onClick={() => switchTab("register")}>
              Create Account
            </button>
          </div>
        )}

        {/* ── Login ── */}
        {tab === "login" && (
          <>
            <OAuthRow onSelect={handleOAuth} />
            {loginSubmit.error && <ErrorBanner message={loginSubmit.error} suggestedFix={loginSubmit.suggestedFix} onRetry={loginForm.isValid ? loginSubmit.retry : undefined} />}
            <form onSubmit={loginForm.handleSubmit} noValidate>
              <EmailField {...loginForm.register("email")} label="Email" required autoFocus autoComplete="email" />
              <PasswordField {...loginForm.register("password")} label="Password" required autoComplete="current-password" />
              <div style={S.row}>
                <Checkbox {...loginForm.registerCheckbox("remember")} label="Remember me" />
                <button type="button" style={S.link}
                  onClick={() => { forgotForm.setValue("email", loginForm.values.email); switchTab("forgot"); }}>
                  Forgot password?
                </button>
              </div>
              <SubmitButton loading={loginSubmit.isSubmitting} loadingText="Signing in…">Sign In</SubmitButton>
            </form>
          </>
        )}

        {/* ── Register ── */}
        {tab === "register" && !registeredEmail && (
          <>
            <OAuthRow onSelect={handleOAuth} />
            {registerSubmit.error && <ErrorBanner message={registerSubmit.error} suggestedFix={registerSubmit.suggestedFix} onRetry={registerForm.isValid ? registerSubmit.retry : undefined} />}
            <form onSubmit={registerForm.handleSubmit} noValidate>
              <TextField {...registerForm.register("name")} label="Name" required autoFocus autoComplete="name" />
              <EmailField {...registerForm.register("email")} label="Email" required autoComplete="email" />
              <PasswordField {...registerForm.register("password")} label="Password" required autoComplete="new-password"
                hint={!registerForm.errors.password ? "Min 8 characters, at least one letter and one number" : undefined} />
              <PasswordField {...registerForm.register("confirmPassword")} label="Confirm Password" required autoComplete="new-password" />
              <SubmitButton loading={registerSubmit.isSubmitting} loadingText="Creating account…">Create Account</SubmitButton>
            </form>
          </>
        )}

        {/* ── Post-registration: resend verification ── */}
        {tab === "register" && registeredEmail && (
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>📧</div>
            <p style={{ color: "var(--t1)", fontWeight: 600, marginBottom: 6 }}>Check your inbox</p>
            <p style={{ color: "var(--t3)", fontSize: 13, marginBottom: 20 }}>
              We sent a verification link to <strong style={{ color: "var(--t2)" }}>{registeredEmail}</strong>.
              Click the link to activate your account.
            </p>
            {resendSubmit.error && <ErrorBanner message={resendSubmit.error} suggestedFix={resendSubmit.suggestedFix} onRetry={resendSubmit.retry} />}
            {resendSubmit.success && <SuccessBanner message="Verification email sent." />}
            <GoldButton disabled={resendSubmit.isSubmitting} onClick={() => switchTab("login")} style={{ width: "100%" }}>
              Go to Sign In
            </GoldButton>
            <button type="button" style={S.btnText} disabled={resendSubmit.isSubmitting} onClick={handleResend}>
              {resendSubmit.isSubmitting ? "Sending…" : "Resend verification email"}
            </button>
          </div>
        )}

        {/* ── Forgot password ── */}
        {tab === "forgot" && (
          <form onSubmit={forgotForm.handleSubmit} noValidate>
            <p style={{ color: "var(--t2)", fontSize: 13, margin: "0 0 16px" }}>
              Enter your email and we'll send a password reset link.
            </p>
            {forgotSubmit.error && <ErrorBanner message={forgotSubmit.error} suggestedFix={forgotSubmit.suggestedFix} onRetry={forgotForm.isValid ? forgotSubmit.retry : undefined} />}
            {forgotSubmit.success && <SuccessBanner message="If that email exists, a reset link is on its way." />}
            <EmailField {...forgotForm.register("email")} label="Email" required autoFocus autoComplete="email" />
            <SubmitButton loading={forgotSubmit.isSubmitting} loadingText="Sending…">Send Reset Link</SubmitButton>
            <button type="button" style={S.btnSecondary} onClick={() => switchTab("login")}>
              Back to Sign In
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
