/**
 * Navigation regression tests.
 *
 * Root cause being guarded against: AppLayout's page switch used a plain
 * synchronous setState. When the target page's lazy chunk hadn't loaded
 * yet, the render attempting to mount it could suspend mid-commit, which
 * left AnimatePresence's children-tracking out of sync with React's actual
 * committed tree — Sidebar (a sibling, unaffected by the suspension) would
 * show the new page as active while <main> kept rendering the previous
 * page's content. Fixed by routing page switches through useTransition
 * (AppContext.tsx) and giving ErrorBoundary a `key={page}` (AppLayout.tsx)
 * so an error on one page can never leak into the next page's view.
 *
 * These tests render the real AppProvider + AppLayout + Sidebar + the real
 * PageTransition/ErrorBoundary/Suspense wiring — only the feature pages
 * and the auth/org contexts are stubbed, since their own data-fetching is
 * not what's under test here.
 *
 * NOTE: Sidebar labels reflect the current Flow redesign nav groups:
 *   Workspace:  Dashboard, App Builder, Templates
 *   Build:      Design Studio, Agents, Automations, Runs, Integrations
 *   Platform:   Data, API, Packages, Analytics
 *   System:     Organizations, Settings
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AppProvider } from "../contexts/AppContext";
import { AppLayout } from "../components/layout/AppLayout";

vi.mock("../contexts/AuthContext", () => ({
  useAuth: () => ({ user: { email: "qa@example.com" }, logout: vi.fn() }),
}));
vi.mock("../contexts/OrgContext", () => ({
  useOrg: () => ({ orgs: [], currentOrgId: null, currentOrg: null, loading: false, setCurrentOrgId: vi.fn(), refreshOrgs: vi.fn(), createOrg: vi.fn() }),
}));

// Toggled per-test to exercise the ErrorBoundary-reset regression guard.
let designShouldThrow = false;

// ── Workspace ──
vi.mock("../features/home", () => ({ HomePage: () => <div>HOME_PAGE_CONTENT</div> }));
vi.mock("../features/app-builder", () => ({ AppBuilderPage: () => <div>APP_BUILDER_PAGE_CONTENT</div> }));
vi.mock("../features/marketplace", () => ({ MarketplacePage: () => <div>MARKETPLACE_PAGE_CONTENT</div> }));

// ── Build ──
vi.mock("../features/design-studio", () => ({
  DesignStudio: () => {
    if (designShouldThrow) throw new Error("Simulated design crash");
    return <div>DESIGN_PAGE_CONTENT</div>;
  },
}));
vi.mock("../features/agentos", () => ({ AgentOSPage: () => <div>AGENTOS_PAGE_CONTENT</div> }));
vi.mock("../features/automation/AutomationPage", () => ({ AutomationPage: () => <div>AUTOMATION_PAGE_CONTENT</div> }));
vi.mock("../features/runs", () => ({ RunsPage: () => <div>RUNS_PAGE_CONTENT</div> }));
vi.mock("../features/integrations", () => ({ IntegrationsPage: () => <div>INTEGRATIONS_PAGE_CONTENT</div> }));

// ── Platform ──
vi.mock("../features/observability", () => ({ ObservabilityPage: () => <div>OBSERVABILITY_PAGE_CONTENT</div> }));
vi.mock("../features/ai-routing", () => ({ AIRoutingPage: () => <div>AI_ROUTING_PAGE_CONTENT</div> }));
vi.mock("../features/plugins", () => ({ PluginsPage: () => <div>PLUGINS_PAGE_CONTENT</div> }));
vi.mock("../features/sandbox", () => ({ SandboxPage: () => <div>SANDBOX_PAGE_CONTENT</div> }));

// ── System ──
vi.mock("../features/organizations", () => ({ OrganizationsPage: () => <div>ORGANIZATIONS_PAGE_CONTENT</div> }));
vi.mock("../features/settings", () => ({ SettingsPage: () => <div>SETTINGS_PAGE_CONTENT</div> }));

// Unused pages (still in app, just not in sidebar nav any more)
vi.mock("../features/ai", () => ({ AIWorkspace: () => <div>AI_PAGE_CONTENT</div> }));
vi.mock("../features/dev", () => ({ DevWorkspace: () => <div>DEV_PAGE_CONTENT</div> }));
vi.mock("../features/social", () => ({ SocialPage: () => <div>SOCIAL_PAGE_CONTENT</div> }));
vi.mock("../features/teams", () => ({ TeamsPage: () => <div>TEAMS_PAGE_CONTENT</div> }));
vi.mock("../features/billing", () => ({ BillingPage: () => <div>BILLING_PAGE_CONTENT</div> }));

function renderApp() {
  return render(
    <AppProvider>
      <AppLayout />
    </AppProvider>,
  );
}

describe("navigation", () => {
  /**
   * All sidebar nav buttons — title attribute matches the i18n label.
   * Label → page content invariant: the content shown must always match
   * the button that's marked aria-current="page".
   */
  it("clicking each sidebar item renders that page and marks it active — never disagreeing", async () => {
    renderApp();
    await screen.findByText("HOME_PAGE_CONTENT");

    // [title in sidebar, expected main content] pairs — all current sidebar items
    const cases: [string, string][] = [
      // Workspace
      ["App Builder",   "APP_BUILDER_PAGE_CONTENT"],
      ["Templates",     "MARKETPLACE_PAGE_CONTENT"],
      // Build
      ["Design Studio", "DESIGN_PAGE_CONTENT"],
      ["Agents",        "AGENTOS_PAGE_CONTENT"],
      ["Automations",   "AUTOMATION_PAGE_CONTENT"],
      ["Runs",          "RUNS_PAGE_CONTENT"],
      ["Integrations",  "INTEGRATIONS_PAGE_CONTENT"],
      // Platform
      ["Data",          "OBSERVABILITY_PAGE_CONTENT"],
      ["API",           "AI_ROUTING_PAGE_CONTENT"],
      ["Packages",      "PLUGINS_PAGE_CONTENT"],
      ["Analytics",     "SANDBOX_PAGE_CONTENT"],
      // System
      ["Organizations", "ORGANIZATIONS_PAGE_CONTENT"],
      ["Settings",      "SETTINGS_PAGE_CONTENT"],
      // Back to home
      ["Dashboard",     "HOME_PAGE_CONTENT"],
    ];

    for (const [label, expectedContent] of cases) {
      const navButton = screen.getByTitle(label);
      fireEvent.click(navButton);

      // The content that actually appears must match the button that's
      // marked active — this is the exact invariant that broke before.
      await waitFor(() => expect(screen.getByText(expectedContent)).toBeInTheDocument());
      expect(navButton).toHaveAttribute("aria-current", "page");
    }
  }, 20000);

  it("survives rapid sequential navigation without ending up on the wrong page", async () => {
    renderApp();
    await screen.findByText("HOME_PAGE_CONTENT");

    // Fire clicks back-to-back with no awaits in between — the scenario
    // that used to desync Sidebar from <main>.
    fireEvent.click(screen.getByTitle("App Builder"));
    fireEvent.click(screen.getByTitle("Runs"));
    fireEvent.click(screen.getByTitle("Integrations"));
    fireEvent.click(screen.getByTitle("Settings"));

    await waitFor(() => expect(screen.getByText("SETTINGS_PAGE_CONTENT")).toBeInTheDocument());
    expect(screen.getByTitle("Settings")).toHaveAttribute("aria-current", "page");
    // No other page's content should be left mounted alongside it.
    expect(screen.queryByText("INTEGRATIONS_PAGE_CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("RUNS_PAGE_CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("APP_BUILDER_PAGE_CONTENT")).not.toBeInTheDocument();
  });

  it("resets ErrorBoundary when navigating away from a page that crashed", async () => {
    designShouldThrow = true;
    renderApp();
    await screen.findByText("HOME_PAGE_CONTENT");

    fireEvent.click(screen.getByTitle("Design Studio"));
    await waitFor(() => expect(screen.getByText(/Error in design/i)).toBeInTheDocument());

    // The crash must not leak into the next page's view.
    fireEvent.click(screen.getByTitle("Dashboard"));
    await waitFor(() => expect(screen.getByText("HOME_PAGE_CONTENT")).toBeInTheDocument());
    expect(screen.queryByText(/Error in design/i)).not.toBeInTheDocument();

    designShouldThrow = false;
  });
});
