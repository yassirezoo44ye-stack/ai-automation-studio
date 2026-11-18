import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../utils/api";
import { useAuth } from "../../contexts/AuthContext";
import { GlassCard } from "../../shared/ui/gold";
import { copyText } from "../../shared/utils/clipboard";

interface SessionRow {
  id: string;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string | null;
  last_used_at: string | null;
}

/** Backend `detail` strings that have a translated message. */
const KNOWN_ERRORS: Record<string, string> = {
  "Current password is incorrect": "account.errors.currentPassword",
  "Invalid authentication code": "account.errors.code",
  "Incorrect password": "account.errors.password",
  "Invalid credentials": "account.errors.password",
  "Email does not match": "account.errors.email",
  "MFA is not enabled": "account.errors.mfaOff",
  "Cannot change password": "account.errors.noPassword",
};

class RequestError extends Error {
  constructor(readonly key: string, readonly detail?: string) { super(key); }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  const text = await res.text().catch(() => "");
  let body: unknown = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = null; }
  if (!res.ok) {
    if (res.status === 429) throw new RequestError("account.errors.rateLimited");
    const raw = (body as { detail?: unknown } | null)?.detail;
    const detail = typeof raw === "string" ? raw
      : Array.isArray(raw) ? String((raw[0] as { msg?: string } | undefined)?.msg ?? "") : "";
    throw new RequestError(KNOWN_ERRORS[detail] ?? "account.errors.generic", detail || undefined);
  }
  return body as T;
}

function useErrorText() {
  const { t } = useTranslation("settings");
  return (err: unknown) => {
    if (err instanceof RequestError) {
      return err.key === "account.errors.generic" && err.detail
        ? `${t(err.key)} (${err.detail})`
        : t(err.key);
    }
    return t("account.errors.generic");
  };
}

function Notice({ kind, children }: { kind: "error" | "success"; children: React.ReactNode }) {
  const color = kind === "error" ? "var(--red)" : "var(--green)";
  return (
    <div role={kind === "error" ? "alert" : "status"} style={{ padding: "10px 14px", borderRadius: 10, background: kind === "error" ? "var(--red-dim)" : "var(--green-dim)", border: `1px solid ${color}`, fontSize: 13, color }}>
      {children}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="section-label" style={{ marginBottom: 12, fontSize: "inherit" }}>{title}</h2>
      <GlassCard lift={false}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>{children}</div>
      </GlassCard>
    </section>
  );
}

function Field({ id, label, ...input }: { id: string; label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label className="g-label" htmlFor={id}>{label}</label>
      <input id={id} className="g-input" style={{ width: "100%" }} {...input} />
    </div>
  );
}

const rowStyle: React.CSSProperties = { display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" };

// ── Profile ──────────────────────────────────────────────────────────────────

function ProfileSection() {
  const { t } = useTranslation("settings");
  const errorText = useErrorText();
  const { user, updateProfile } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      await updateProfile({ name: name.trim() });
      setMsg({ kind: "success", text: t("account.profile.saved") });
    } catch (err) {
      setMsg({ kind: "error", text: err instanceof Error && err.message ? `${t("account.errors.generic")} (${err.message})` : errorText(err) });
    } finally { setBusy(false); }
  }

  return (
    <Section title={t("account.profile.title")}>
      <form onSubmit={e => void save(e)} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field id="account-email" label={t("account.profile.email")} value={user?.email ?? ""} readOnly dir="ltr" />
        <Field id="account-name" label={t("account.profile.name")} value={name} onChange={e => setName(e.target.value)} maxLength={100} required autoComplete="name" />
        {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
        <div><button type="submit" className="g-btn g-btn--primary" disabled={busy || !name.trim() || name.trim() === (user?.name ?? "")}>{busy ? t("account.saving") : t("account.profile.save")}</button></div>
      </form>
    </Section>
  );
}

// ── Password ─────────────────────────────────────────────────────────────────

function PasswordSection({ onSignedOut }: { onSignedOut: () => void }) {
  const { t } = useTranslation("settings");
  const errorText = useErrorText();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  const tooShort = next.length > 0 && next.length < 8;
  const mismatch = confirm.length > 0 && next !== confirm;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (tooShort || mismatch || !current) return;
    setBusy(true); setMsg(null);
    try {
      await call("/api/auth/me/password", { method: "PUT", body: JSON.stringify({ current_password: current, new_password: next }) });
      setMsg({ kind: "success", text: t("account.password.changed") });
      // The backend revokes every session after a password change.
      setTimeout(onSignedOut, 2500);
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    } finally { setBusy(false); }
  }

  return (
    <Section title={t("account.password.title")}>
      <form onSubmit={e => void submit(e)} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field id="pw-current" type="password" label={t("account.password.current")} value={current} onChange={e => setCurrent(e.target.value)} autoComplete="current-password" required />
        <Field id="pw-new" type="password" label={t("account.password.new")} value={next} onChange={e => setNext(e.target.value)} autoComplete="new-password" minLength={8} maxLength={128} required aria-describedby="pw-hint" />
        <div id="pw-hint" style={{ fontSize: 11, color: tooShort ? "var(--red)" : "var(--t4)", marginTop: -8 }}>{t("account.password.hint")}</div>
        <Field id="pw-confirm" type="password" label={t("account.password.confirm")} value={confirm} onChange={e => setConfirm(e.target.value)} autoComplete="new-password" required />
        {mismatch && <div style={{ fontSize: 11, color: "var(--red)", marginTop: -8 }}>{t("account.password.mismatch")}</div>}
        <div style={{ fontSize: 12, color: "var(--t4)" }}>{t("account.password.signOutNote")}</div>
        {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
        <div><button type="submit" className="g-btn g-btn--primary" disabled={busy || !current || next.length < 8 || next !== confirm}>{busy ? t("account.saving") : t("account.password.submit")}</button></div>
      </form>
    </Section>
  );
}

// ── MFA ──────────────────────────────────────────────────────────────────────

function BackupCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const { t } = useTranslation("settings");
  const [copied, setCopied] = useState(false);
  return (
    <div role="status" style={{ padding: 14, borderRadius: 10, background: "var(--green-dim)", border: "1px solid var(--green)", display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--green)" }}>{t("account.mfa.backupTitle")}</div>
      <div style={{ fontSize: 12, color: "var(--t3)" }}>{t("account.mfa.backupWarning")}</div>
      <ul dir="ltr" style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))", gap: 6, fontFamily: "var(--font-mono)", fontSize: 13 }}>
        {codes.map(c => <li key={c}>{c}</li>)}
      </ul>
      <div style={rowStyle}>
        <button type="button" className="g-btn g-btn--ghost" onClick={() => { void copyText(codes.join("\n")).then(() => setCopied(true)).catch(() => {}); }}>{copied ? t("apiKeys.copied") : t("apiKeys.copy")}</button>
        <button type="button" className="g-btn g-btn--ghost" onClick={onDone}>{t("account.mfa.backupSaved")}</button>
      </div>
    </div>
  );
}

function MfaSection({ enabled, hasPassword, onChanged }: { enabled: boolean; hasPassword: boolean; onChanged: () => Promise<void> }) {
  const { t } = useTranslation("settings");
  const errorText = useErrorText();
  const [setup, setSetup] = useState<{ secret: string; provisioning_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [mode, setMode] = useState<"idle" | "disable" | "regenerate">("idle");

  const reset = () => { setCode(""); setPassword(""); setError(null); };

  async function run(fn: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await fn(); } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }

  const startSetup = () => run(async () => {
    setSetup(await call<{ secret: string; provisioning_uri: string }>("/api/auth/mfa/setup", { method: "POST" }));
  });
  const enable = (e: React.FormEvent) => { e.preventDefault(); void run(async () => {
    const out = await call<{ backup_codes: string[] }>("/api/auth/mfa/enable", { method: "POST", body: JSON.stringify({ code }) });
    setSetup(null); reset(); setBackupCodes(out.backup_codes); await onChanged();
  }); };
  const disable = (e: React.FormEvent) => { e.preventDefault(); void run(async () => {
    await call("/api/auth/mfa/disable", { method: "POST", body: JSON.stringify(hasPassword ? { code, password } : { code }) });
    setMode("idle"); reset(); await onChanged();
  }); };
  const regenerate = (e: React.FormEvent) => { e.preventDefault(); void run(async () => {
    const out = await call<{ backup_codes: string[] }>("/api/auth/mfa/backup-codes", { method: "POST", body: JSON.stringify({ code }) });
    setMode("idle"); reset(); setBackupCodes(out.backup_codes);
  }); };

  const codeField = (
    <Field id="mfa-code" label={t("account.mfa.code")} value={code} onChange={e => setCode(e.target.value.replace(/\s/g, ""))}
      inputMode="numeric" autoComplete="one-time-code" maxLength={8} required dir="ltr" />
  );

  return (
    <Section title={t("account.mfa.title")}>
      <div style={{ ...rowStyle, justifyContent: "space-between" }}>
        <span style={{ fontSize: 13, color: "var(--t3)" }}>{t("account.mfa.description")}</span>
        <span className={`badge badge-${enabled ? "green" : "muted"}`}>{enabled ? t("account.mfa.on") : t("account.mfa.off")}</span>
      </div>
      {backupCodes && <BackupCodes codes={backupCodes} onDone={() => setBackupCodes(null)} />}
      {error && <Notice kind="error">{error}</Notice>}

      {!enabled && !setup && (
        <div><button type="button" className="g-btn g-btn--primary" disabled={busy} onClick={() => void startSetup()}>{t("account.mfa.setup")}</button></div>
      )}

      {!enabled && setup && (
        <form onSubmit={enable} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <ol style={{ margin: 0, paddingInlineStart: 18, fontSize: 13, color: "var(--t3)", display: "flex", flexDirection: "column", gap: 6 }}>
            <li>{t("account.mfa.step1")}</li>
            <li>{t("account.mfa.step2")}</li>
          </ol>
          <code dir="ltr" style={{ fontFamily: "var(--font-mono)", fontSize: 13, padding: "8px 10px", borderRadius: 7, background: "var(--bg-input)", border: "1px solid var(--b1)", wordBreak: "break-all", color: "var(--t2)" }}>{setup.secret}</code>
          <div style={rowStyle}>
            <button type="button" className="g-btn g-btn--ghost" onClick={() => { void copyText(setup.secret).catch(() => {}); }}>{t("account.mfa.copySecret")}</button>
            <a className="g-btn g-btn--ghost" href={setup.provisioning_uri}>{t("account.mfa.openApp")}</a>
          </div>
          {codeField}
          <div style={rowStyle}>
            <button type="submit" className="g-btn g-btn--primary" disabled={busy || code.length < 6}>{t("account.mfa.enable")}</button>
            <button type="button" className="g-btn g-btn--ghost" onClick={() => { setSetup(null); reset(); }}>{t("account.cancel")}</button>
          </div>
        </form>
      )}

      {enabled && mode === "idle" && (
        <div style={rowStyle}>
          <button type="button" className="g-btn g-btn--ghost" onClick={() => { reset(); setMode("regenerate"); }}>{t("account.mfa.regenerate")}</button>
          <button type="button" className="g-btn g-btn--danger" onClick={() => { reset(); setMode("disable"); }}>{t("account.mfa.disable")}</button>
        </div>
      )}

      {enabled && mode !== "idle" && (
        <form onSubmit={mode === "disable" ? disable : regenerate} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ fontSize: 13, color: "var(--t3)" }}>{mode === "disable" ? t("account.mfa.disableHint") : t("account.mfa.regenerateHint")}</div>
          {codeField}
          {mode === "disable" && hasPassword && (
            <Field id="mfa-password" type="password" label={t("account.password.current")} value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required />
          )}
          <div style={rowStyle}>
            <button type="submit" className={`g-btn ${mode === "disable" ? "g-btn--danger" : "g-btn--primary"}`} disabled={busy || code.length < 6 || (mode === "disable" && hasPassword && !password)}>
              {mode === "disable" ? t("account.mfa.disableConfirm") : t("account.mfa.regenerate")}
            </button>
            <button type="button" className="g-btn g-btn--ghost" onClick={() => { setMode("idle"); reset(); }}>{t("account.cancel")}</button>
          </div>
        </form>
      )}
    </Section>
  );
}

// ── Sessions ─────────────────────────────────────────────────────────────────

function SessionsSection({ onSignedOut }: { onSignedOut: () => void }) {
  const { t, i18n } = useTranslation("settings");
  const errorText = useErrorText();
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);

  const load = useCallback(async () => {
    try { setSessions(await call<SessionRow[]>("/api/auth/sessions")); setError(null); }
    catch (err) { setError(errorText(err)); setSessions([]); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { void load(); }, [load]);

  const fmt = (iso: string | null) => iso ? new Date(iso).toLocaleString(i18n.language) : "—";

  async function revoke(id: string) {
    setBusy(id); setError(null);
    try { await call(`/api/auth/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }); setSessions(s => (s ?? []).filter(x => x.id !== id)); }
    catch (err) { setError(errorText(err)); }
    finally { setBusy(null); }
  }

  async function signOutEverywhere() {
    setBusy("all"); setError(null);
    try { await call("/api/auth/logout-all", { method: "POST" }); onSignedOut(); }
    catch (err) { setError(errorText(err)); setBusy(null); }
  }

  return (
    <Section title={t("account.sessions.title")}>
      <div style={{ fontSize: 13, color: "var(--t3)" }}>{t("account.sessions.description")}</div>
      {error && <Notice kind="error">{error}</Notice>}
      {sessions === null ? (
        <div style={{ fontSize: 13, color: "var(--t4)" }}>{t("account.loading")}</div>
      ) : sessions.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--t4)" }}>{t("account.sessions.empty")}</div>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          {sessions.map(s => (
            <li key={s.id} style={{ ...rowStyle, justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--b1)" }}>
              <div style={{ minWidth: 0, flex: "1 1 200px" }}>
                <div dir="ltr" style={{ fontSize: 13, color: "var(--t2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "start" }}>{s.user_agent || t("account.sessions.unknownDevice")}</div>
                <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 2 }}>
                  <span dir="ltr">{s.ip_address ?? "—"}</span> · {t("account.sessions.lastUsed")} {fmt(s.last_used_at ?? s.created_at)}
                </div>
              </div>
              <button type="button" className="g-btn g-btn--ghost" disabled={busy !== null} onClick={() => void revoke(s.id)}>{t("account.sessions.revoke")}</button>
            </li>
          ))}
        </ul>
      )}
      {confirmAll ? (
        <div style={rowStyle}>
          <span style={{ fontSize: 13, color: "var(--t3)" }}>{t("account.sessions.confirmAll")}</span>
          <button type="button" className="g-btn g-btn--danger" disabled={busy !== null} onClick={() => void signOutEverywhere()}>{t("account.sessions.signOutAll")}</button>
          <button type="button" className="g-btn g-btn--ghost" onClick={() => setConfirmAll(false)}>{t("account.cancel")}</button>
        </div>
      ) : (
        <div><button type="button" className="g-btn g-btn--danger" onClick={() => setConfirmAll(true)}>{t("account.sessions.signOutAll")}</button></div>
      )}
    </Section>
  );
}

// ── Delete account ───────────────────────────────────────────────────────────

function DeleteSection({ email, hasPassword, onDeleted }: { email: string; hasPassword: boolean; onDeleted: () => void }) {
  const { t } = useTranslation("settings");
  const errorText = useErrorText();
  const [open, setOpen] = useState(false);
  const [typedEmail, setTypedEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await call("/api/auth/me", { method: "DELETE", body: JSON.stringify({ email: typedEmail.trim(), password }) });
      onDeleted();
    } catch (err) { setError(errorText(err)); setBusy(false); }
  }

  return (
    <Section title={t("account.delete.title")}>
      <div style={{ fontSize: 13, color: "var(--t3)" }}>{t("account.delete.description")}</div>
      {!hasPassword ? (
        <div style={{ fontSize: 13, color: "var(--t4)" }}>{t("account.delete.oauthNote")}</div>
      ) : !open ? (
        <div><button type="button" className="g-btn g-btn--danger" onClick={() => setOpen(true)}>{t("account.delete.start")}</button></div>
      ) : (
        <form onSubmit={e => void submit(e)} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field id="delete-email" label={t("account.delete.typeEmail", { email })} value={typedEmail} onChange={e => setTypedEmail(e.target.value)} autoComplete="off" dir="ltr" required />
          <Field id="delete-password" type="password" label={t("account.password.current")} value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required />
          {error && <Notice kind="error">{error}</Notice>}
          <div style={rowStyle}>
            <button type="submit" className="g-btn g-btn--danger" disabled={busy || typedEmail.trim().toLowerCase() !== email.toLowerCase() || !password}>{t("account.delete.confirm")}</button>
            <button type="button" className="g-btn g-btn--ghost" onClick={() => { setOpen(false); setTypedEmail(""); setPassword(""); setError(null); }}>{t("account.cancel")}</button>
          </div>
        </form>
      )}
    </Section>
  );
}

// ── Tab ──────────────────────────────────────────────────────────────────────

export function AccountSecurityTab() {
  const { t } = useTranslation("settings");
  const { user, logout, refreshUser } = useAuth();

  if (!user) {
    return (
      <GlassCard lift={false}>
        <div style={{ fontSize: 13, color: "var(--t4)" }}>{t("account.signedOut")}</div>
      </GlassCard>
    );
  }

  const hasPassword = user.has_password !== false;
  const signOut = () => { void logout(); };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 600, animation: "slideUp .2s ease" }}>
      <ProfileSection />
      {hasPassword && <PasswordSection onSignedOut={signOut} />}
      <MfaSection enabled={!!user.mfa_enabled} hasPassword={hasPassword} onChanged={refreshUser} />
      <SessionsSection onSignedOut={signOut} />
      <DeleteSection email={user.email} hasPassword={hasPassword} onDeleted={signOut} />
    </div>
  );
}
