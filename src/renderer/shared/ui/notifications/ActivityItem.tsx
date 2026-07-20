import { memo } from "react";
import type { TimelineEntry } from "./ActivityTimeline";

const GROUP_LABEL: Record<string, string> = { security: "Security", organization: "Organization" };

function ActivityItemImpl({ entry }: { entry: TimelineEntry }) {
  return (
    <div className="g-activity-item">
      <span className={`g-activity-item__badge g-activity-item__badge--${entry.group}`}>
        {GROUP_LABEL[entry.group] ?? entry.group}
      </span>
      <span className="g-activity-item__action">{entry.action}</span>
      {entry.sub && <span className="g-activity-item__sub">{entry.sub}</span>}
      <span className="g-activity-item__time">
        {new Date(entry.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      </span>
    </div>
  );
}

export const ActivityItem = memo(ActivityItemImpl);
