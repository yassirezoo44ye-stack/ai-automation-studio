import { useTranslation } from "react-i18next";
import AxonLogo from "../../AxonLogo";
import { parseJSON } from "../../utils/api";
import { useForm } from "../../shared/forms/useForm";
import { useAsyncSubmit } from "../../shared/forms/useAsyncSubmit";
import { all, required, minLength, matchesField, passwordStrength } from "../../shared/forms/validators";
import { PasswordField, SubmitButton, ErrorBanner, SuccessBanner } from "../../shared/ui/forms";
import { GoldButton } from "../../shared/ui/gold";

const API = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

// Same visual language as AuthPage.tsx (S.wrap/card/logo/title/sub/btnSecondary) —
// duplicated locally rather than exported/shared, since AuthPage's S object isn't
// exported and this page is reached via a public email link, not the login tabs.
const S = {
  wrap: {
    display: "flex", alignItems: "center", justifyContent: "center",
    minHeight: "100vh",
    background: "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(110,50,224,0.12) 0%, var(--bg-base) 70%)",
    fontFamily: "var(--font-sans)",
    padding: "24px",
  } as React.CSSProperties,
  card: {
    background: "var(--bg-elevated)", border: "1px solid var(--b1)",
    borderRadius: 20, padding: "40px 36px", width: "100%", maxWidth: 420,
    boxShadow: "var(--shadow-xl)",
  } as React.CSSProperties,
  logo:  { display: "flex", justifyContent: "center", marginBottom: 12 } as React.CSSProperties,
  title: { margin: "0 0 2px", fontSize: 22, fontWeight: 700, color: "var(--t1)", textAlign: "center" } as React.CSSProperties,
  sub:   { margin: "0 0 24px", fontSize: 13, color: "var(--t3)", textAlign: "center" } as React.CSSProperties,
  btnSecondary: {
    width: "100%", padding: "10px", borderRadius: 10, marginTop: 8,
    border: "1px solid var(--b1)", background: "transparent",
    color: "var(--t3)", fontSize: 13, cursor: "pointer",
  } as React.CSSProperties,
};

interface ResetValues { password: string; confirmPassword: string }

function goToLogin() {
  // Full navigation, not an in-SPA state change — this page is reached from
  // outside any authenticated session (no refresh token in localStorage),
  // so there's no AuthContext state to reconcile; a plain reload of "/"
  // lands cleanly on the normal !user -> AuthPage gate in App.tsx.
  window.location.href = "/";
}

export function ResetPasswordPage() {
  const { t } = useTranslation("auth");
  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  const resetSubmit = useAsyncSubmit<{ message: string }>();
  const resetForm = useForm<ResetValues>({
    initialValues: { password: "", confirmPassword: "" },
    validators: {
      password: all(required(t("validation.passwordRequired")), minLength(8), passwordStrength()),
      confirmPassword: all(required(t("validation.confirmRequired")), matchesField("password", t("validation.passwordsMismatch"))),
    },
    onValid: values => resetSubmit.run(async signal => {
      const res = await fetch(`${API}/api/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password: values.password }),
        signal,
      });
      return parseJSON<{ message: string }>(res, "/api/auth/reset-password");
    }),
  });

  return (
    <div style={S.wrap}>
      <div style={S.card}>
        <div style={S.logo}><AxonLogo size={56} /></div>
        <h1 style={S.title}>{t("reset.title")}</h1>

        {!token ? (
          // No token in the URL at all (page opened directly, not via the
          // email link) -- same class of failure as an expired/invalid
          // token, so it gets the same clean, non-crashing terminal state
          // without even attempting the API call.
          <>
            <p style={S.sub}>{t("reset.invalidLink")}</p>
            <GoldButton onClick={goToLogin} style={{ width: "100%" }}>{t("verify.goToSignIn")}</GoldButton>
          </>
        ) : resetSubmit.success ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
            <SuccessBanner message={t("reset.success")} />
            <GoldButton onClick={goToLogin} style={{ width: "100%", marginTop: 16 }}>
              {t("verify.goToSignIn")}
            </GoldButton>
          </div>
        ) : (
          <form onSubmit={resetForm.handleSubmit} noValidate>
            <p style={S.sub}>{t("reset.intro")}</p>
            {resetSubmit.error && (
              <ErrorBanner
                message={resetSubmit.error}
                suggestedFix={resetSubmit.suggestedFix}
                onRetry={resetForm.isValid ? resetSubmit.retry : undefined}
              />
            )}
            <PasswordField
              {...resetForm.register("password")}
              label={t("reset.newPassword")}
              required autoFocus autoComplete="new-password"
              hint={!resetForm.errors.password ? t("register.passwordHint") : undefined}
            />
            <PasswordField
              {...resetForm.register("confirmPassword")}
              label={t("reset.confirmPassword")}
              required autoComplete="new-password"
            />
            <SubmitButton loading={resetSubmit.isSubmitting} loadingText={t("reset.submitting")}>
              {t("reset.submit")}
            </SubmitButton>
            <button type="button" style={S.btnSecondary} onClick={goToLogin}>
              {t("forgot.backToSignIn")}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
