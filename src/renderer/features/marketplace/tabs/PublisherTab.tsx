import { C } from "../../../shared/lib/theme";
/**
 * PublisherTab — publisher profile (display name, verified badge, item
 * count). Legacy listings with no owner org fall back to the free-text
 * `author` field. Data: GET /marketplace/publishers/{org_id}
 */
import { useState, useEffect } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";

interface Publisher {
  id: string;
  organization_id: string;
  display_name: string;
  verified: boolean;
  item_count: number;
}

export function PublisherTab({ ownerOrganizationId, author }: {
  ownerOrganizationId: string | null;
  author: string;
}) {
  const [publisher, setPublisher] = useState<Publisher | null | undefined>(undefined);

  // Reset while switching listings/owners — render-time adjustment.
  const [prevOwner, setPrevOwner] = useState(ownerOrganizationId);
  if (prevOwner !== ownerOrganizationId) {
    setPrevOwner(ownerOrganizationId);
    setPublisher(ownerOrganizationId ? undefined : null);
  }

  useEffect(() => {
    if (!ownerOrganizationId) return;
    let alive = true;
    (async () => {
      try {
        const r = await apiFetch(`/marketplace/publishers/${ownerOrganizationId}`);
        if (!r.ok) throw new Error();
        const d = await parseJSON<Publisher>(r, "publisher");
        if (alive) setPublisher(d);
      } catch { if (alive) setPublisher(null); }
    })();
    return () => { alive = false; };
  }, [ownerOrganizationId]);

  if (publisher === undefined) return <div style={{ fontSize: 12, color: "var(--t4)" }}>Loading publisher…</div>;

  if (publisher === null) {
    return (
      <div style={{ fontSize: 12, color: "var(--t4)" }}>
        Published by <strong style={{ color: "var(--t2)" }}>{author}</strong> — no publisher profile on file for this legacy listing.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <div style={{
        width: 40, height: 40, borderRadius: 10, background: "rgba(108,142,247,.12)",
        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0,
      }}>
        🏢
      </div>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)" }}>{publisher.display_name}</span>
          {publisher.verified && (
            <span style={{ fontSize: 10, fontWeight: 700, color: C.green, background: "rgba(52,211,153,.12)", padding: "1px 6px", borderRadius: 99 }}>
              VERIFIED
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: "var(--t4)" }}>
          {publisher.item_count} listing{publisher.item_count === 1 ? "" : "s"} published
        </div>
      </div>
    </div>
  );
}
