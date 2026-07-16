import { useState, useCallback } from "react";
import { ToastCtx } from "./ToastContext";
import type { Toast, ToastKind } from "./ToastContext";

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const add = useCallback((msg: string, kind: ToastKind = "ok") => {
    const id = crypto.randomUUID();
    setToasts(p => [...p, { id, msg, kind }]);
    setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 3800);
  }, []);
  const dismiss = useCallback((id: string) => setToasts(p => p.filter(t => t.id !== id)), []);
  const toastIcon = { ok: "✓", err: "✕", info: "i" };
  return (
    <ToastCtx.Provider value={add}>
      {children}
      <div style={{ position: "fixed", bottom: 24, right: 24, display: "flex", flexDirection: "column", gap: 8, zIndex: 9999 }}>
        {toasts.map(t => (
          <div key={t.id} className={`toast toast-${t.kind}`} role="alert" aria-live="polite">
            <span className="toast-icon" style={{ fontWeight: 700, fontSize: 12, width: 18, height: 18, borderRadius: "50%", border: "1.5px solid currentColor", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{toastIcon[t.kind]}</span>
            <span className="toast-body">{t.msg}</span>
            <button onClick={() => dismiss(t.id)} style={{ background: "none", border: "none", cursor: "pointer", color: "currentColor", opacity: 0.5, padding: "0 0 0 4px", fontSize: 16, lineHeight: 1, flexShrink: 0 }} aria-label="Dismiss">×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
