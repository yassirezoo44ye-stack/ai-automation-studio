import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../../shared/utils/api";

interface StackItem { id: string; category: string; name: string; referral: boolean }

/** Optional, collapsed. Clicks are recorded by an authenticated call that
 *  only resolves ids configured on the server. Referral entries are disclosed. */
export function RecommendedStack() {
  const { t } = useTranslation("appBuilder");
  const [items, setItems] = useState<StackItem[] | null>(null);
  const [error, setError] = useState(false);
  async function load() {
    if (items) return;
    setError(false);
    try {
      const response = await apiFetch("/api/recommended-stack");
      if (!response.ok) throw new Error("unavailable");
      setItems(((await response.json()) as { items: StackItem[] }).items);
    } catch { setError(true); }
  }
  async function open(id: string) {
    try {
      const response = await apiFetch(`/api/recommended-stack/click/${encodeURIComponent(id)}`, { method: "POST" });
      if (!response.ok) throw new Error("unavailable");
      const { url } = await response.json() as { url: string };
      if (!url.startsWith("https://")) throw new Error("invalid");
      window.open(url, "_blank", "noopener,noreferrer");
    } catch { setError(true); }
  }
  const hasReferral = items?.some(item => item.referral);
  return <details style={{ padding: "8px 16px", fontSize: 12 }} onToggle={event => { if ((event.currentTarget as HTMLDetailsElement).open) void load(); }}>
    <summary>{t("stack.title")}</summary>
    {error && <p role="alert">{t("stack.unavailable")}</p>}
    {items && items.length === 0 && <p>{t("stack.empty")}</p>}
    {items && items.length > 0 && <>
      <ul style={{ listStyle: "none", padding: 0, margin: "8px 0" }}>
        {items.map(item => <li key={item.id}>
          <span>{t(`stack.category.${item.category}`)}: </span>
          <button type="button" onClick={() => void open(item.id)}>{item.name}{item.referral ? ` (${t("stack.referral")})` : ""}</button>
        </li>)}
      </ul>
      {hasReferral && <p role="note">{t("stack.disclosure")}</p>}
    </>}
  </details>;
}
