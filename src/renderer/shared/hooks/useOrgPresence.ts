/**
 * useOrgPresence — online/offline status for an org's members.
 *
 * The live NotificationContext socket only carries *changes* (see
 * contexts/NotificationContext.tsx's presence: frame handling) — it has no
 * way to know who was already online before this client connected. This
 * hook fetches that one-time snapshot from GET /api/orgs/{id}/presence and
 * merges it with the live delta set, so callers get a single `isOnline()`
 * that's correct from first render onward.
 */
import { useEffect, useState } from "react";
import { apiJSON } from "../utils/api";
import { useNotifications } from "../../contexts/notifications";

export function useOrgPresence(organizationId: string | null) {
  const { presenceDeltas } = useNotifications();
  const [snapshot, setSnapshot] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    if (!organizationId) {
      void Promise.resolve().then(() => { if (!cancelled) setSnapshot({}); });
      return () => { cancelled = true; };
    }
    void apiJSON<{ presence: Record<string, boolean> }>(`/api/orgs/${organizationId}/presence`)
      .then(res => { if (!cancelled) setSnapshot(res.presence); })
      .catch(() => { if (!cancelled) setSnapshot({}); });
    return () => { cancelled = true; };
  }, [organizationId]);

  // A live delta always wins over the snapshot — it's a real-time report of
  // exactly this user's status; the snapshot is only a fallback for users
  // this client hasn't been told about a change for yet.
  const isOnline = (userId: string): boolean =>
    presenceDeltas.has(userId) ? presenceDeltas.get(userId)! : (snapshot[userId] ?? false);

  return { isOnline };
}
