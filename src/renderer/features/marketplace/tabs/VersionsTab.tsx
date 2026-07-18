import { C } from "../../../shared/lib/theme";
/**
 * VersionsTab — version history, release notes, structured changelog, and
 * (for orgs with marketplace:install permission) a rollback action.
 * Data: GET /marketplace/listings/{id}/versions
 *       GET /marketplace/listings/{id}/versions/{version}/changelog
 *       POST /marketplace/listings/{id}/rollback
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/toast";

interface VersionEntry { id: string; version: string; changelog: string | null; created_at: string | number }
interface ChangelogEntry { id: string; change_type: string; description: string; sort_order: number }

const CHANGE_COLOR: Record<string, string> = {
  added: C.green, changed: C.blue, fixed: C.amber, removed: C.redSoft, security: "#e879f9",
};

export function VersionsTab({ listingId, currentVersion, canManage, onRolledBack }: {
  listingId: string;
  currentVersion: string;
  canManage: boolean;
  onRolledBack: () => void;
}) {
  const toast = useToast();
  const [versions, setVersions] = useState<VersionEntry[] | null>(null);
  const [changelogs, setChangelogs] = useState<Record<string, ChangelogEntry[]>>({});
  const [rollingBack, setRollingBack] = useState<string | null>(null);

  // Reset while switching listings — render-time state adjustment.
  const [prevListingId, setPrevListingId] = useState(listingId);
  if (prevListingId !== listingId) { setPrevListingId(listingId); setVersions(null); }

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await apiFetch(`/marketplace/listings/${listingId}/versions`);
        if (!r.ok) throw new Error();
        const d = await parseJSON<VersionEntry[]>(r, "versions");
        if (alive) setVersions(d);
      } catch { if (alive) setVersions([]); }
    })();
    return () => { alive = false; };
  }, [listingId]);

  const loadChangelog = useCallback(async (version: string) => {
    if (changelogs[version]) return;
    try {
      const r = await apiFetch(`/marketplace/listings/${listingId}/versions/${version}/changelog`);
      if (!r.ok) return;
      const d = await parseJSON<ChangelogEntry[]>(r, "changelog");
      setChangelogs(prev => ({ ...prev, [version]: d }));
    } catch { /* best-effort */ }
  }, [listingId, changelogs]);

  const rollback = async (version: string) => {
    setRollingBack(version);
    try {
      const r = await apiFetch(`/marketplace/listings/${listingId}/rollback`, {
        method: "POST",
        body: JSON.stringify({ target_version: version }),
      });
      if (!r.ok) throw new Error();
      toast(`Rolled back to v${version}`, "ok");
      onRolledBack();
    } catch {
      toast("Rollback failed", "err");
    } finally {
      setRollingBack(null);
    }
  };

  if (versions === null) return <div style={{ fontSize: 12, color: "var(--t4)" }}>Loading versions…</div>;
  if (versions.length === 0) return <div style={{ fontSize: 12, color: "var(--t4)" }}>No version history yet.</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {versions.map(v => (
        <div key={v.id} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "10px 12px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)" }}>v{v.version}</span>
              {v.version === currentVersion && (
                <span style={{ fontSize: 10, fontWeight: 700, color: C.green, background: "rgba(52,211,153,.12)", padding: "1px 6px", borderRadius: 99 }}>
                  CURRENT
                </span>
              )}
            </div>
            {canManage && v.version !== currentVersion && (
              <button
                onClick={() => void rollback(v.version)}
                disabled={rollingBack === v.version}
                style={{
                  padding: "4px 10px", borderRadius: 6, border: "1px solid var(--border)",
                  background: "rgba(255,255,255,.04)", color: "var(--t3)", fontSize: 11,
                  cursor: rollingBack === v.version ? "wait" : "pointer", whiteSpace: "nowrap",
                }}
              >
                {rollingBack === v.version ? "…" : "Rollback to this version"}
              </button>
            )}
          </div>
          {v.changelog && <p style={{ fontSize: 12, color: "var(--t3)", margin: "6px 0 0" }}>{v.changelog}</p>}
          <button
            onClick={() => void loadChangelog(v.version)}
            style={{ marginTop: 6, background: "none", border: "none", color: "var(--accent-2)", fontSize: 11, cursor: "pointer", padding: 0 }}
          >
            {changelogs[v.version] ? null : "Show structured changelog"}
          </button>
          {changelogs[v.version] && changelogs[v.version].length > 0 && (
            <ul style={{ margin: "6px 0 0", paddingLeft: 16 }}>
              {changelogs[v.version].map(c => (
                <li key={c.id} style={{ fontSize: 11, color: "var(--t3)" }}>
                  <span style={{ color: CHANGE_COLOR[c.change_type] ?? "var(--t4)", fontWeight: 700, textTransform: "uppercase", fontSize: 10 }}>
                    {c.change_type}
                  </span>{" "}
                  {c.description}
                </li>
              ))}
            </ul>
          )}
          {changelogs[v.version] && changelogs[v.version].length === 0 && (
            <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 4 }}>No structured changelog entries for this version.</div>
          )}
        </div>
      ))}
    </div>
  );
}
