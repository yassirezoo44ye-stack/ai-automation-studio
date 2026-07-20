export interface ActivityGroup { id: string; label: string }

export function ActivityFilter({ groups, active, onChange }: {
  groups: ActivityGroup[];
  active: string | null;
  onChange: (id: string | null) => void;
}) {
  return (
    <div className="g-notif-panel__filters" style={{ borderBottom: "none", padding: "0 0 12px" }} role="tablist" aria-label="Filter activity">
      <button
        type="button"
        role="tab"
        aria-selected={active === null}
        className={`g-notif-chip ${active === null ? "g-notif-chip--active" : ""}`}
        onClick={() => onChange(null)}
      >
        All
      </button>
      {groups.map(g => (
        <button
          key={g.id}
          type="button"
          role="tab"
          aria-selected={active === g.id}
          className={`g-notif-chip ${active === g.id ? "g-notif-chip--active" : ""}`}
          onClick={() => onChange(g.id)}
        >
          {g.label}
        </button>
      ))}
    </div>
  );
}
