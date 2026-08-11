import { useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const STATS = [
  { label: "Active Automations", value: 0 },
  { label: "Published Today", value: 0 },
  { label: "Scheduled", value: 0 },
  { label: "Failed", value: 0 },
  { label: "AI Usage (tokens)", value: 0 },
  { label: "Estimated Cost", value: "$0.00" },
];

export function DashboardPage() {
  const { user, organizations } = useAuth();
  const location = useLocation() as { state?: { draftPrompt?: string } };
  const draftPrompt = location.state?.draftPrompt;

  return (
    <div className="page">
      <div className="dashboard">
        <h1>Welcome back{user ? `, ${user.full_name}` : ""}</h1>

        <div className="section-title">Your workspaces</div>
        <div className="org-list">
          {organizations.map((org) => (
            <span className="org-chip" key={org.id}>
              {org.name}
              <span className="role">{org.role}</span>
            </span>
          ))}
        </div>

        {draftPrompt && (
          <>
            <div className="section-title">Your prompt</div>
            <div className="notice-card">
              <strong>"{draftPrompt}"</strong>
              <p style={{ margin: "0.5rem 0 0" }}>
                Natural-language automation planning (topic/frequency/duration extraction,
                content-strategy generation, and scheduling) ships in Phase 2–3 of this build.
                Your prompt hasn't been discarded — this screen is just honest that nothing has
                been generated or scheduled from it yet.
              </p>
            </div>
          </>
        )}

        <div className="section-title">Overview</div>
        <div className="dashboard-grid">
          {STATS.map((stat) => (
            <div className="stat-card" key={stat.label}>
              <div className="stat-value">{stat.value}</div>
              <div className="stat-label">{stat.label}</div>
            </div>
          ))}
        </div>

        <div className="section-title">Upcoming</div>
        <div className="notice-card">
          No scheduled posts yet. The scheduler, queue, and publishing engine land in Phase 3–4.
        </div>
      </div>
    </div>
  );
}
