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
 * NOTE: Sidebar labels reflect the simplified nav (7 items only):
 *   Main:    Home, My AI, Build an App, Design, Automate, Marketing
 *   Account: Settings
 *
 * Developer/admin pages (Agents, Runs, Monitoring, Logs, AI Gateway,
 * Integrations, Packages, Marketplace, Organizations, Teams, Billing)
 * are intentionally hidden from the sidebar; they remain in the app
 * and are still exercised via AppContext.setPage() when needed.
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

// Pages now in sidebar nav
vi.mock("../features/ai", () => ({ AIWorkspace: () => <div>AI_PAGE_CONTENT</div> }));
vi.mock("../features/teams", () => ({ TeamsPage: () => <div>TEAMS_PAGE_CONTENT</div> }));
vi.mock("../features/billing", () => ({ BillingPage: () => <div>BILLING_PAGE_CONTENT</div> }));

// Unused pages (still in app, just not in sidebar nav)
vi.mock("../features/dev", () => ({ DevWorkspace: () => <div>DEV_PAGE_CONTENT</div> }));
vi.mock("../features/social", () => ({ SocialPage: () => <div>SOCIAL_PAGE_CONTENT</div> }));

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
    // Default page is now app-builder (first screen the user sees after login)
    await screen.findByText("APP_BUILDER_PAGE_CONTENT", {}, { timeout: 8000 });

    // [title in sidebar, expected main content] pairs — simplified sidebar only
    const cases: [string, string][] = [
      // Main tools
      ["Home",         "HOME_PAGE_CONTENT"],
      ["My AI",        "AI_PAGE_CONTENT"],
      ["Design",       "DESIGN_PAGE_CONTENT"],
      ["Automate",     "AUTOMATION_PAGE_CONTENT"],
      ["Marketing",    "SOCIAL_PAGE_CONTENT"],
      // Account
      ["Settings",     "SETTINGS_PAGE_CONTENT"],
      // Back to app-builder
      ["Build an App", "APP_BUILDER_PAGE_CONTENT"],
    ];

    for (const [label, expectedContent] of cases) {
      const navButton = screen.getByTitle(label);
      fireEvent.click(navButton);

      // The content that actually appears must match the button that's
      // marked active — this is the exact invariant that broke before.
      // Use a longer timeout to account for lazy-chunk loading latency
      // in the full test suite (worker contention can delay Suspense resolution).
      await waitFor(() => expect(screen.getByText(expectedContent)).toBeInTheDocument(), { timeout: 8000 });
      expect(navButton).toHaveAttribute("aria-current", "page");
    }
  }, 60000);

  it("survives rapid sequential navigation without ending up on the wrong page", async () => {
    renderApp();
    await screen.findByText("APP_BUILDER_PAGE_CONTENT", {}, { timeout: 8000 });

    // Fire clicks back-to-back with no awaits in between — the scenario
    // that used to desync Sidebar from <main>.
    fireEvent.click(screen.getByTitle("Home"));
    fireEvent.click(screen.getByTitle("Design"));
    fireEvent.click(screen.getByTitle("Automate"));
    fireEvent.click(screen.getByTitle("Settings"));


    await waitFor(() => expect(screen.getByText("SETTINGS_PAGE_CONTENT")).toBeInTheDocument(), { timeout: 8000 });
    expect(screen.getByTitle("Settings")).toHaveAttribute("aria-current", "page");
    // No other page's content should be left mounted alongside it.
    expect(screen.queryByText("HOME_PAGE_CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("DESIGN_PAGE_CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("AUTOMATION_PAGE_CONTENT")).not.toBeInTheDocument();
  });

  it("resets ErrorBoundary when navigating away from a page that crashed", async () => {
    designShouldThrow = true;
    renderApp();
    await screen.findByText("APP_BUILDER_PAGE_CONTENT", {}, { timeout: 8000 });

    fireEvent.click(screen.getByTitle("Design"));
    await waitFor(() => expect(screen.getByText(/Error in design/i)).toBeInTheDocument(), { timeout: 8000 });

    // The crash must not leak into the next page's view.
    fireEvent.click(screen.getByTitle("Build an App"));
    await waitFor(() => expect(screen.getByText("APP_BUILDER_PAGE_CONTENT")).toBeInTheDocument(), { timeout: 8000 });
    expect(screen.queryByText(/Error in design/i)).not.toBeInTheDocument();

    designShouldThrow = false;
  });
});
