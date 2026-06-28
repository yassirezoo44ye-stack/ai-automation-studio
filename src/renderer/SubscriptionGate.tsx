import { useState, useEffect } from "react";

const API = import.meta.env.VITE_API_URL ?? "";

interface Props {
  children: React.ReactNode;
}

export default function SubscriptionGate({ children }: Props) {
  const [checking, setChecking] = useState(true);
  const [active, setActive] = useState(false);
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const savedEmail = localStorage.getItem("sub_email") ?? "";

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("subscribed") === "1" && savedEmail) {
      verifyEmail(savedEmail).then(() => {
        window.history.replaceState({}, "", "/");
      });
    } else if (savedEmail) {
      verifyEmail(savedEmail);
    } else {
      setChecking(false);
    }
  }, []);

  async function verifyEmail(e: string) {
    setChecking(true);
    try {
      const res = await fetch(`${API}/api/subscription/status?email=${encodeURIComponent(e)}`);
      const data = await res.json();
      if (data.active) {
        setActive(true);
      }
    } catch {
      // offline — skip gate
      setActive(true);
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
    localStorage.setItem("sub_email", email);
    await verifyEmail(email);
    setLoading(false);
    if (!active) setError("لا يوجد اشتراك نشط لهذا البريد");
  }

  if (checking) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: "#0a0a0f", color: "#fff" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>⚡</div>
          <p style={{ color: "#888" }}>جارٍ التحقق من الاشتراك...</p>
        </div>
      </div>
    );
  }

  if (active) return <>{children}</>;

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
        {/* Logo */}
        <div style={{ fontSize: 56, marginBottom: 8 }}>🤖</div>
        <h1 style={{ margin: "0 0 8px", fontSize: 26, fontWeight: 700 }}>
          AI Automation Studio
        </h1>
        <p style={{ color: "#888", margin: "0 0 32px", fontSize: 14 }}>
          منصة الأتمتة الذكية بالذكاء الاصطناعي
        </p>

        {/* Price badge */}
        <div style={{
          background: "linear-gradient(135deg, #6c63ff, #a855f7)",
          borderRadius: 50, display: "inline-block",
          padding: "6px 24px", marginBottom: 32
        }}>
          <span style={{ fontSize: 28, fontWeight: 800 }}>$1</span>
          <span style={{ fontSize: 14, marginRight: 4, opacity: 0.9 }}>/شهر فقط</span>
        </div>

        {/* Features */}
        <div style={{ textAlign: "right", marginBottom: 32 }}>
          {[
            "🤖 وكلاء ذكاء اصطناعي غير محدودة",
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

        {/* Email input */}
        <input
          type="email"
          placeholder="بريدك الإلكتروني"
          value={email}
          onChange={e => setEmail(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleSubscribe()}
          style={{
            width: "100%", padding: "12px 16px", borderRadius: 10,
            border: "1px solid #2a2a3a", background: "#1a1a2e",
            color: "#fff", fontSize: 15, marginBottom: 12,
            boxSizing: "border-box", direction: "ltr", textAlign: "left"
          }}
        />

        {error && <p style={{ color: "#f87171", fontSize: 13, margin: "0 0 12px" }}>{error}</p>}

        {/* Subscribe button */}
        <button
          onClick={handleSubscribe}
          disabled={loading}
          style={{
            width: "100%", padding: "14px", borderRadius: 10,
            background: loading ? "#3a3a5a" : "linear-gradient(135deg, #6c63ff, #a855f7)",
            color: "#fff", fontSize: 16, fontWeight: 700,
            border: "none", cursor: loading ? "not-allowed" : "pointer",
            marginBottom: 12, transition: "opacity 0.2s"
          }}
        >
          {loading ? "جارٍ التحويل..." : "اشترك الآن — $1/شهر 🚀"}
        </button>

        {/* Already subscribed */}
        <button
          onClick={handleCheckEmail}
          disabled={loading}
          style={{
            width: "100%", padding: "11px", borderRadius: 10,
            background: "transparent", color: "#888", fontSize: 14,
            border: "1px solid #2a2a3a", cursor: "pointer"
          }}
        >
          لديك اشتراك بالفعل؟ تحقق
        </button>

        <p style={{ color: "#555", fontSize: 12, marginTop: 20 }}>
          دفع آمن عبر Stripe • إلغاء في أي وقت
        </p>
      </div>
    </div>
  );
}
