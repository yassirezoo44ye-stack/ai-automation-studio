/**
 * AIRoutingPage — tab shell for Providers/Models/Budgets/Cost Analytics/
 * Usage Reports. Mirrors BillingPage.tsx's tab-shell pattern (same design
 * system — S from styles/theme). Each tab fetches its own data; Cost
 * Analytics and Usage Reports reuse the already-built costClient
 * (core/ai/platform/CostClient.ts) rather than hand-rolling new fetches.
 */
import { useState } from "react";
import { useOrg } from "../../contexts/OrgContext";
import { S } from "../../styles/theme";
import { ProvidersTab } from "./tabs/ProvidersTab";
import { ModelsTab } from "./tabs/ModelsTab";
import { BudgetsTab } from "./tabs/BudgetsTab";
import { CostAnalyticsTab } from "./tabs/CostAnalyticsTab";
import { UsageReportsTab } from "./tabs/UsageReportsTab";

type Tab = "providers" | "models" | "budgets" | "cost" | "usage";

const TABS: { id: Tab; label: string }[] = [
  { id: "providers", label: "Providers" },
  { id: "models", label: "Models" },
  { id: "budgets", label: "Budgets" },
  { id: "cost", label: "Cost Analytics" },
  { id: "usage", label: "Usage Reports" },
];

export function AIRoutingPage() {
  const { currentOrgId, orgs } = useOrg();
  const [tab, setTab] = useState<Tab>("providers");

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>AI Routing</span>
        <span style={S.headerSub}>Providers, model catalog, budgets, and real spend from ai_usage_log</span>
      </header>

      <div style={{ display: "flex", gap: 6, padding: "12px 24px 0" }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{ ...(tab === t.id ? S.btnPrimary : S.btnSecondary), padding: "7px 14px", fontSize: 12 }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {tab === "providers" ? (
          <ProvidersTab />
        ) : tab === "models" ? (
          <ModelsTab />
        ) : tab === "budgets" ? (
          currentOrgId ? (
            <BudgetsTab orgId={currentOrgId} />
          ) : (
            <div className="empty-state" style={{ margin: "auto" }}>
              <div style={{ fontSize: 40 }}>💰</div>
              <h3>No organization selected</h3>
              <p>{orgs.length === 0 ? "Create an organization first." : "Pick one from the Organizations page."}</p>
            </div>
          )
        ) : tab === "cost" ? (
          <CostAnalyticsTab />
        ) : (
          <UsageReportsTab />
        )}
      </div>
    </>
  );
}
