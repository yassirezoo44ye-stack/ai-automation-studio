import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { OrgProvider }   from "./contexts/OrgContext";
import { AppProvider }   from "./contexts/AppContext";
import { LangProvider }  from "./contexts/LangContext";
import { ToastProvider } from "./contexts/ToastContext";
import { NotificationProvider } from "./contexts/NotificationContext";
import { CopilotProvider } from "./contexts/CopilotContext";
import { AppLayout }     from "./components/layout/AppLayout";
import { AuthPage }      from "./features/auth/AuthPage";
import { ResetPasswordPage } from "./features/auth/ResetPasswordPage";
import { LoadingSpinner } from "./shared/ui/LoadingSpinner";
import "./design-system.css";

// Keep Render free tier awake
const API = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
setInterval(() => fetch(`${API}/health`).catch(() => {}), 14 * 60 * 1000);

function AppInner() {
  const { user, loading, bootstrapError } = useAuth();

  // Reached from the password-reset email link (app/core/email.py:
  // `${APP_URL}/reset-password?token=...`) -- a fully logged-out visitor
  // with no stored session, so it's handled before the auth-bootstrap
  // gates below rather than waiting on `loading`/`user` to resolve.
  if (window.location.pathname === "/reset-password") {
    return <ResetPasswordPage />;
  }

  if (loading) {
    return <LoadingSpinner fullPage label="Starting Flow…" />;
  }

  if (bootstrapError) {
    return (
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        height: "100vh", background: "var(--bg-base)", color: "var(--t3)",
        fontFamily: "system-ui, sans-serif",
      }}>
        <div style={{ textAlign: "center", maxWidth: 360 }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>⚠️</div>
          <p style={{ fontSize: 15, color: "var(--t1)", marginBottom: 8 }}>Connection error</p>
          <p style={{ fontSize: 13, marginBottom: 20 }}>{bootstrapError}</p>
          <button
            onClick={() => window.location.reload()}
            style={{ padding: "9px 20px", borderRadius: 8, border: "none", background: "var(--accent)", color: "#fff", cursor: "pointer", fontSize: 14 }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!user) {
    return <AuthPage />;
  }

  return (
    <ToastProvider>
      <OrgProvider>
        <AppProvider>
          <NotificationProvider>
            <CopilotProvider>
              <AppLayout />
            </CopilotProvider>
          </NotificationProvider>
        </AppProvider>
      </OrgProvider>
    </ToastProvider>
  );
}

export default function App() {
  return (
    <LangProvider>
      <AuthProvider>
        <AppInner />
      </AuthProvider>
    </LangProvider>
  );
}
