/**
 * ConfigTab — a JSON editor for the plugin's config, validated server-side
 * against its manifest's configuration_schema (a hand-rolled JSON-Schema
 * subset check — see app/plugins/manifest.py). A raw JSON textarea rather
 * than a generated form: reuses the existing design system's plain-input
 * patterns without building a dynamic-schema-to-form generator, which is
 * out of scope for this phase.
 */
import { useState } from "react";
import { apiFetch } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/ToastContext";

export function ConfigTab({ installationId, config }: { installationId: string; config: Record<string, unknown> }) {
  const toast = useToast();
  const [text, setText] = useState(() => JSON.stringify(config, null, 2));
  const [saving, setSaving] = useState(false);

  const save = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      toast("Invalid JSON", "err");
      return;
    }
    setSaving(true);
    try {
      const r = await apiFetch(`/plugins/installed/${installationId}/config`, {
        method: "PUT",
        body: JSON.stringify({ config: parsed }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body?.detail?.errors?.join("; ") ?? "Save failed");
      }
      toast("Configuration saved", "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Save failed", "err");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        rows={10}
        spellCheck={false}
        style={{
          width: "100%", boxSizing: "border-box", background: "var(--bg-base)",
          border: "1px solid var(--border)", borderRadius: 8, color: "var(--t1)",
          fontSize: 12, fontFamily: "monospace", padding: 10, resize: "vertical",
        }}
      />
      <button
        onClick={() => void save()}
        disabled={saving}
        style={{
          alignSelf: "flex-start", padding: "6px 16px", borderRadius: 6, border: "none",
          cursor: saving ? "wait" : "pointer", background: "linear-gradient(135deg,#FFD700,#D4AF37)",
          color: "#0a0a0a", fontSize: 12, fontWeight: 700,
        }}
      >
        {saving ? "…" : "Save Configuration"}
      </button>
    </div>
  );
}
