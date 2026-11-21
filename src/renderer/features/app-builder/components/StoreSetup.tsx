import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../../shared/utils/api";

export function StoreSetup({ projectId }: { projectId: string }) {
  const { t } = useTranslation("appBuilder");
  const [token, setToken] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  async function reveal() {
    setBusy(true); setError(false);
    try {
      const response = await apiFetch(`/api/projects/${projectId}/store-setup`);
      if (!response.ok) throw new Error("Setup unavailable");
      const data = await response.json() as { token: string };
      setToken(data.token);
    } catch { setError(true); }
    finally { setBusy(false); }
  }
  return <div style={{ padding: "8px 16px", fontSize: 12 }}>
    <span style={{ marginInlineEnd: 12 }}>{t("runtime.expires")}</span>
    <button type="button" disabled={busy} onClick={() => { if (token) setToken(""); else void reveal(); }}>{t("commerce.setup")}</button>
    {token && <div><p>{t("commerce.instructions")}</p><code style={{ overflowWrap: "anywhere", userSelect: "all" }}>{token}</code></div>}
    {error && <p role="alert">{t("commerce.unavailable")}</p>}
  </div>;
}
