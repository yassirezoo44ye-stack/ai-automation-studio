/**
 * ActivityTimeline — generic, day-grouped audit/activity feed. Presentational
 * only: the caller owns fetching (different callers hit different endpoints,
 * e.g. /api/auth/me/audit-log vs /api/orgs/{org_id}/activity) and passes in
 * a normalized entry list.
 */
import { useMemo, useState } from "react";
import { LoadingSpinner } from "../LoadingSpinner";
import { ErrorState } from "../StateViews";
import { EmptyState } from "../StateViews";
import { ActivityItem } from "./ActivityItem";
import { ActivityFilter, type ActivityGroup } from "./ActivityFilter";

export interface TimelineEntry {
  id: string;
  action: string;
  sub?: string | null;
  created_at: string;
  /** Which source/category this entry belongs to — drives the filter chips and badge color. */
  group: string;
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yest = new Date(today); yest.setDate(today.getDate() - 1);
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (sameDay(d, today)) return "Today";
  if (sameDay(d, yest)) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
}

export function ActivityTimeline({
  entries, groups, status, error, onRetry, emptyMessage = "No activity recorded yet.",
}: {
  entries: TimelineEntry[];
  groups: ActivityGroup[];
  status: "loading" | "success" | "error";
  error?: string | null;
  onRetry?: () => void;
  emptyMessage?: string;
}) {
  const [activeGroup, setActiveGroup] = useState<string | null>(null);

  const filtered = useMemo(
    () => activeGroup ? entries.filter(e => e.group === activeGroup) : entries,
    [entries, activeGroup],
  );

  const days = useMemo(() => {
    const byDay = new Map<string, TimelineEntry[]>();
    for (const e of filtered) {
      const label = dayLabel(e.created_at);
      if (!byDay.has(label)) byDay.set(label, []);
      byDay.get(label)!.push(e);
    }
    return [...byDay.entries()];
  }, [filtered]);

  if (status === "loading") return <LoadingSpinner label="Loading activity…" />;
  if (status === "error") return <ErrorState compact message={error ?? "Failed to load activity."} onRetry={onRetry ?? (() => {})} />;

  return (
    <div>
      {groups.length > 0 && <ActivityFilter groups={groups} active={activeGroup} onChange={setActiveGroup} />}
      {filtered.length === 0 ? (
        <EmptyState compact title="Nothing here yet" description={emptyMessage} />
      ) : (
        <div className="g-activity-timeline">
          {days.map(([label, dayEntries]) => (
            <div key={label} className="g-activity-day">
              <div className="g-activity-day__label">{label}</div>
              {dayEntries.map(e => <ActivityItem key={e.id} entry={e} />)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
