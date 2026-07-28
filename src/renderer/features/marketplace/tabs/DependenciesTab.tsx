/**
 * DependenciesTab — required/optional dependency list with version
 * constraints. Data: GET /marketplace/listings/{id}/dependencies
 */
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseJSON } from "../../../shared/utils/api";

interface Dependency {
  id: string;
  item_id: string;
  depends_on_item_id: string;
  version_constraint: string;
  optional: boolean;
}

export function DependenciesTab({ listingId }: { listingId: string }) {
  const { t } = useTranslation("marketplace");
  const [deps, setDeps] = useState<Dependency[] | null>(null);
  // Reset while switching listings — render-time state adjustment.
  const [prevListingId, setPrevListingId] = useState(listingId);
  if (prevListingId !== listingId) { setPrevListingId(listingId); setDeps(null); }

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await apiFetch(`/marketplace/listings/${listingId}/dependencies`);
        if (!r.ok) throw new Error();
        const d = await parseJSON<Dependency[]>(r, "dependencies");
        if (alive) setDeps(d);
      } catch { if (alive) setDeps([]); }
    })();
    return () => { alive = false; };
  }, [listingId]);

  if (deps === null) return <div style={{ fontSize: 12, color: "var(--t4)" }}>{t("dependencies.loading")}</div>;
  if (deps.length === 0) return <div style={{ fontSize: 12, color: "var(--t4)" }}>{t("dependencies.empty")}</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {deps.map(d => (
        <div
          key={d.id}
          style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            border: "1px solid var(--border)", borderRadius: 8, padding: "8px 12px",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--t2)", fontFamily: "monospace" }}>{d.depends_on_item_id}</span>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "var(--t4)" }}>{d.version_constraint}</span>
            <span style={{
              fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 99,
              background: d.optional ? "var(--bg-card)" : "var(--accent-dim)",
              color: d.optional ? "var(--t4)" : "var(--accent-2)",
            }}>
              {d.optional ? t("dependencies.optional") : t("dependencies.required")}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
