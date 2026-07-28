/**
 * ObservabilityPage — tab shell for the Enterprise Observability &
 * Monitoring phase. Mirrors AIRoutingPage.tsx's tab-shell pattern (same
 * design system — S from styles/theme). Every tab reads real backend
 * data from app/routers/diagnostics_api.py, app/routers/health.py,
 * app/routers/auth_users.py, and app/routers/organizations.py — nothing
 * here is mocked. Deep per-domain data (AI cost breakdown, org billing,
 * per-plugin detail, per-worker sandbox logs) stays on its existing page;
 * tabs here link out rather than duplicating those views.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { S } from "../../styles/theme";
import { GoldButton } from "../../shared/ui/gold";
import { SystemOverviewTab } from "./tabs/SystemOverviewTab";
import { AIAnalyticsTab } from "./tabs/AIAnalyticsTab";
import { WorkflowAnalyticsTab } from "./tabs/WorkflowAnalyticsTab";
import { MarketplaceAnalyticsTab } from "./tabs/MarketplaceAnalyticsTab";
import { BillingAnalyticsTab } from "./tabs/BillingAnalyticsTab";
import { PluginHealthTab } from "./tabs/PluginHealthTab";
import { SandboxMonitoringTab } from "./tabs/SandboxMonitoringTab";
import { EventBusTab } from "./tabs/EventBusTab";
import { SecurityAuditTab } from "./tabs/SecurityAuditTab";
import { AlertsTracesTab } from "./tabs/AlertsTracesTab";

type Tab =
  | "system" | "ai" | "workflow" | "marketplace" | "billing"
  | "plugins" | "sandbox" | "events" | "security" | "alerts";

const TAB_IDS: Tab[] = ["system", "ai", "workflow", "marketplace", "billing", "plugins", "sandbox", "events", "security", "alerts"];

export function ObservabilityPage() {
  const { t } = useTranslation("observability");
  const [tab, setTab] = useState<Tab>("system");

  return (
    <>
      <header style={S.header}>
        <span style={S.headerTitle}>{t("page.title")}</span>
        <span style={S.headerSub}>{t("page.subtitle")}</span>
      </header>

      <div style={{ display: "flex", gap: 6, padding: "12px 24px 0", flexWrap: "wrap" }}>
        {TAB_IDS.map(id => (
          <GoldButton
            key={id}
            variant={tab === id ? "primary" : "ghost"}
            onClick={() => setTab(id)}
            style={{ padding: "7px 14px", fontSize: 12 }}
          >
            {t(`tabs.${id}`)}
          </GoldButton>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 24 }}>
        {tab === "system" ? <SystemOverviewTab /> :
         tab === "ai" ? <AIAnalyticsTab /> :
         tab === "workflow" ? <WorkflowAnalyticsTab /> :
         tab === "marketplace" ? <MarketplaceAnalyticsTab /> :
         tab === "billing" ? <BillingAnalyticsTab /> :
         tab === "plugins" ? <PluginHealthTab /> :
         tab === "sandbox" ? <SandboxMonitoringTab /> :
         tab === "events" ? <EventBusTab /> :
         tab === "security" ? <SecurityAuditTab /> :
         <AlertsTracesTab />}
      </div>
    </>
  );
}
