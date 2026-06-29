import { useState, useEffect } from "react";
import AxonLogo from "./AxonLogo";

const API = import.meta.env.VITE_API_URL ?? "";
const TRIAL_DAYS = 7;

interface Props {
  children: React.ReactNode;
}

interface AccessState {
  active: boolean;
  trial: boolean;
  daysRemaining: number;
}

export default function SubscriptionGate({ children }: Props) {
  const [checking, setChecking] = useState(true);
  const [access, setAccess] = useState<AccessState | null>(null);
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showBanner, setShowBanner] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const savedEmail = localStorage.getItem("sub_email") ?? "";
    const savedToken = localStorage.getItem("sub_token") ?? "";

    if (params.get("subscribed") === "1" && savedEmail) {
      window.history.replaceState({}, "", "/");
      fetchStatus(savedEmail);
    } else if (savedToken) {
      verifyToken(savedToken);
    } else if (savedEmail) {
      fetchStatus(savedEmail);
    } else {
      setChecking(false);
    }
  }, []);

  async function verifyToken(token: string) {
    setChecking(true);
    try {
      const res = await fetch(`${API}/api/subscription/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const data = await res.json();
      if (data.valid) {
        localStorage.setItem("sub_token", data.token);
        setAccess({ active: true, trial: data.trial, daysRemaining: data.days_remaining ?? 0 });
      }
      // invalid token → fall through, access stays null → show gate
    } catch {
      // network error — keep gate closed
    } finally {
      setChecking(false);
    }
  }

  async function fetchStatus(e: string) {
    setChecking(true);
    try {
      const res = await fetch(`${API}/api/subscription/status?email=${encodeURIComponent(e)}`);
      const data = await res.json();
      if (data.active && data.token) {
        localStorage.setItem("sub_email", e);
        localStorage.setItem("sub_token", data.token);
        setAccess({ active: true, trial: data.trial ?? false, daysRemaining: data.days_remaining ?? 0 });
      }
      // inactive/expired → gate shown
    } catch {
      // keep gate closed on network error
    } finally {
      setChecking(false);
    }
  }

  async function handleSubscribe() {
    if (!email.includes("@")) { setError("أدخل بريد إلكتروني صحيح"); return; }
    setError("");
    setLoading(true);
    try {
      localStorage.setItem("sub_email", email);
      const res = await fetch(`${API}/api/subscription/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) throw new Error(await res.text());
      const { url } = await res.json();
      window.location.href = url;
    } catch (e: any) {
      setError(e.message ?? "حدث خطأ");
      setLoading(false);
    }
  }

  async function handleCheckEmail() {
    if (!email.includes("@")) { setError("أدخل بريد إلكتروني صحيح"); return; }
    setError("");
    setLoading(true);
    await fetchStatus(email);
    setLoading(false);
    if (!access) setError("لا يوجد اشتراك أو تجربة مجانية نشطة لهذا البريد");
  }

  if (checking) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: "#0a0a0f", color: "#fff" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>⚡</div>
          <p style={{ color: "#888" }}>جارٍ التحقق...</p>
        </div>
      </div>
    );
  }

  if (access?.active) {
    const bannerBg = access.trial ? "linear-gradient(90deg,#7c3aed,#6366f1)" : "linear-gradient(90deg,#059669,#0d9488)";
    const bannerText = access.trial
      ? `تجربة مجانية — ${access.daysRemaining} يوم${access.daysRemaining === 1 ? "" : "ًا"} متبقية من ${TRIAL_DAYS}`
      : "اشتراك نشط ✓";

    return (
      <>
        {access.trial && showBanner && (
          <div style={{
            position: "fixed", top: 0, left: 0, right: 0, zIndex: 9999,
            background: bannerBg, color: "#fff", fontSize: 13, fontWeight: 600,
            display: "flex", alignItems: "center", justifyContent: "center", gap: 16,
            padding: "8px 16px", fontFamily: "system-ui, sans-serif",
          }}>
            <span>🎁 {bannerText}</span>
            <button
              onClick={() => {
                const savedEmail = localStorage.getItem("sub_email") ?? "";
                setEmail(savedEmail);
                setAccess(null);
              }}
              style={{ background: "rgba(255,255,255,.2)", border: "none", color: "#fff", borderRadius: 6, padding: "3px 10px", cursor: "pointer", fontSize: 12 }}
            >
              اشترك الآن
            </button>
            <button onClick={() => setShowBanner(false)} style={{ background: "none", border: "none", color: "rgba(255,255,255,.7)", cursor: "pointer", fontSize: 16 }}>×</button>
          </div>
        )}
        <div style={{ paddingTop: access.trial && showBanner ? 38 : 0 }}>
          {children}
        </div>
      </>
    );
  }

  // Gate — not active (trial expired or never started)
  const trialExpired = !access?.active;

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      height: "100vh", background: "#0a0a0f", color: "#fff",
      fontFamily: "system-ui, sans-serif", direction: "rtl"
    }}>
      <div style={{
        background: "#12121a", border: "1px solid #2a2a3a", borderRadius: 20,
        padding: "48px 40px", maxWidth: 420, width: "90%", textAlign: "center"
      }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
          <AxonLogo size={72} />
        </div>
        <h1 style={{ margin: "0 0 8px", fontSize: 26, fontWeight: 700 }}>Axon</h1>
        <p style={{ color: "#888", margin: "0 0 24px", fontSize: 14 }}>
          منصة الأتمتة الذكية بالذكاء الاصطناعي
        </p>

        <div style={{
          background: "linear-gradient(135deg,#6c63ff,#a855f7)",
          borderRadius: 50, display: "inline-flex", alignItems: "baseline", gap: 4,
          padding: "6px 24px", marginBottom: 8
        }}>
          <span style={{ fontSize: 28, fontWeight: 800 }}>$1</span>
          <span style={{ fontSize: 14, opacity: 0.9 }}>/شهر فقط</span>
        </div>
        <p style={{ color: "#6c63ff", fontSize: 13, margin: "0 0 28px", fontWeight: 600 }}>
          🎁 جرّب مجاناً {TRIAL_DAYS} أيام — لا حاجة لبطاقة بنكية
        </p>

        <div style={{ textAlign: "right", marginBottom: 28 }}>
          {[
            "🧠 وكلاء ذكاء اصطناعي غير محدودة",
            "💬 محادثات مع Claude AI",
            "🎨 استوديو التصميم",
            "📦 تحزيم تطبيقات Python",
            "📱 أتمتة وسائل التواصل",
            "🚀 بناء تطبيقات تلقائي",
          ].map(f => (
            <div key={f} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, fontSize: 14, color: "#ccc" }}>
              <span>{f}</span>
            </div>
          ))}
        </div>

        <input
          type="email"
          placeholder="بريدك الإلكتروني"
          value={email}
          onChange={e => setEmail(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleCheckEmail()}
          style={{
            width: "100%", padding: "12px 16px", borderRadius: 10,
            border: "1px solid #2a2a3a", background: "#1a1a2e",
            color: "#fff", fontSize: 15, marginBottom: 12,
            boxSizing: "border-box", direction: "ltr", textAlign: "left"
          }}
        />

        {error && <p style={{ color: "#f87171", fontSize: 13, margin: "0 0 12px" }}>{error}</p>}

        <button
          onClick={handleCheckEmail}
          disabled={loading}
          style={{
            width: "100%", padding: "14px", borderRadius: 10,
            background: loading ? "#3a3a5a" : "linear-gradient(135deg,#6c63ff,#a855f7)",
            color: "#fff", fontSize: 16, fontWeight: 700,
            border: "none", cursor: loading ? "not-allowed" : "pointer",
            marginBottom: 10,
          }}
        >
          {loading ? "جارٍ التحقق..." : "ابدأ التجربة المجانية 🚀"}
        </button>

        <button
          onClick={handleSubscribe}
          disabled={loading}
          style={{
            width: "100%", padding: "11px", borderRadius: 10,
            background: "transparent", color: "#888", fontSize: 14,
            border: "1px solid #2a2a3a", cursor: "pointer", marginBottom: 10,
          }}
        >
          اشترك مباشرة بـ $1/شهر
        </button>

        <p style={{ color: "#555", fontSize: 12, marginTop: 8 }}>
          دفع آمن عبر Stripe • إلغاء في أي وقت
        </p>
      </div>
    </div>
  );
}
