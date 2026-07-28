/**
 * AIRoutingPage — tab shell for Providers/Models/Budgets/Cost Analytics/
 * Usage Reports. Mirrors BillingPage.tsx's tab-shell pattern (same design
 * system — S from styles/theme). Each tab fetches its own data; Cost
 * Analytics and Usage Reports reuse the already-built costClient
 * (core/ai/platform/CostClient.ts) rather than hand-rolling new fetches.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useOrg } from "../../contexts/OrgContext";
import { S } from "../../styles/theme";
import { GoldButton } from "../../shared/ui/gold";
import { EmptyState } from "../../shared/ui/EmptyState";
import { ProvidersTab } from "./tabs/ProvidersTab";
import { ModelsTab } from "./tabs/ModelsTab";
import { BudgetsTab } from "./tabs/BudgetsTab";
import { CostAnalyticsTab } from "./tabs/CostAnalyticsTab";
import { UsageReportsTab } from "./tabs/UsageReportsTab";

type Tab = "providers" | "models" | "budgets" | "cost" | "usage";

export function AIRoutingPage() {
  const { t } = useTranslation("aiRouting");
  const { currentOrgId, orgs } = useOrg();
  const [tab, setTab] = useState<Tab>("providers");

  const TABS: { id: Tab; label: string }[] = [
    { id: "providers", label: t("tabs.providers") },
    { id: "models", label: t("tabs.models") },
    { id: "budgets", label: t("tabs.budgets") },
    { id: "cost", label: t("tabs.cost") },
    { id: "usage", label: t("tabs.usage") },
  ];

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>{t("page.title")}</span>
        <span style={S.headerSub}>{t("page.subtitle")}</span>
      </header>

      <div style={{ display: "flex", gap: 6, padding: "12px 24px 0" }}>
        {TABS.map(tabDef => (
          <GoldButton
            key={tabDef.id}
            variant={tab === tabDef.id ? "primary" : "ghost"}
            onClick={() => setTab(tabDef.id)}
            style={{ padding: "7px 14px", fontSize: 12 }}
          >
            {tabDef.label}
          </GoldButton>
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
            <EmptyState
              icon={<span style={{ fontSize: 40 }}>💰</span>}
              title={t("noOrgState.title")}
              description={orgs.length === 0 ? t("noOrgState.descriptionNoOrgs") : t("noOrgState.descriptionPickOne")}
            />
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
