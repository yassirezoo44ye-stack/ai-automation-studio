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
 * NOTE: Sidebar labels reflect the consolidated nav (target structure):
 *   Main:     Home, My AI Assistant, Flow Feed
 *   Create:   New Project
 *   Run:      Leads, Automate, Devices
 *   Discover: Discover
 *   System:   Teams, Billing, Settings
 *
 * All other pages (app-builder, design, saas-factory, business-lab, and all
 * admin/platform pages) are intentionally hidden from the sidebar; they
 * remain in the app and are still reachable via direct URL or command palette.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { AppProvider } from "../contexts/AppContext";
import { AppLayout } from "../components/layout/AppLayout";

vi.mock("../contexts/AuthContext", () => ({
  useAuth: () => ({ user: { email: "qa@example.com" }, logout: vi.fn() }),
}));
vi.mock("../contexts/OrgContext", () => ({
  useOrg: () => ({ orgs: [], currentOrgId: null, currentOrg: null, loading: false, setCurrentOrgId: vi.fn(), refreshOrgs: vi.fn(), createOrg: vi.fn() }),
}));

// Toggled per-test to exercise the ErrorBoundary-reset regression guard.
let newProjectShouldThrow = false;

// ── Workspace ──
vi.mock("../features/home", () => ({ HomePage: () => <div>HOME_PAGE_CONTENT</div> }));
vi.mock("../features/app-builder", () => ({ AppBuilderPage: () => <div>APP_BUILDER_PAGE_CONTENT</div> }));
vi.mock("../features/marketplace", () => ({ MarketplacePage: () => <div>MARKETPLACE_PAGE_CONTENT</div> }));

// ── Create / Build ──
vi.mock("../features/new-project/NewProjectPage", () => ({
  NewProjectPage: () => {
    if (newProjectShouldThrow) throw new Error("Simulated new-project crash");
    return <div>NEW_PROJECT_PAGE_CONTENT</div>;
  },
}));
vi.mock("../features/design-studio", () => ({ DesignStudio: () => <div>DESIGN_PAGE_CONTENT</div> }));
vi.mock("../features/saas-factory", () => ({ SaasFactoryPage: () => <div>SAAS_FACTORY_PAGE_CONTENT</div> }));
vi.mock("../features/business-lab", () => ({ BusinessLabPage: () => <div>BUSINESS_LAB_PAGE_CONTENT</div> }));

// ── Run ──
vi.mock("../features/leads", () => ({ LeadsPage: () => <div>LEADS_PAGE_CONTENT</div> }));
vi.mock("../features/devices", () => ({ DevicesPage: () => <div>DEVICES_PAGE_CONTENT</div> }));
vi.mock("../features/agentos", () => ({ AgentOSPage: () => <div>AGENTOS_PAGE_CONTENT</div> }));
vi.mock("../features/automation/AutomationPage", () => ({ AutomationPage: () => <div>AUTOMATION_PAGE_CONTENT</div> }));
vi.mock("../features/runs", () => ({ RunsPage: () => <div>RUNS_PAGE_CONTENT</div> }));
vi.mock("../features/integrations", () => ({ IntegrationsPage: () => <div>INTEGRATIONS_PAGE_CONTENT</div> }));

// ── Discover / Feed ──
vi.mock("../features/discover", () => ({ DiscoverPage: () => <div>DISCOVER_PAGE_CONTENT</div> }));
vi.mock("../features/feed", () => ({ FeedPage: () => <div>FEED_PAGE_CONTENT</div> }));

// ── Platform ──
vi.mock("../features/observability", () => ({ ObservabilityPage: () => <div>OBSERVABILITY_PAGE_CONTENT</div> }));
vi.mock("../features/ai-routing", () => ({ AIRoutingPage: () => <div>AI_ROUTING_PAGE_CONTENT</div> }));
vi.mock("../features/plugins", () => ({ PluginsPage: () => <div>PLUGINS_PAGE_CONTENT</div> }));
vi.mock("../features/sandbox", () => ({ SandboxPage: () => <div>SANDBOX_PAGE_CONTENT</div> }));
vi.mock("../features/training-studio", () => ({ TrainingStudioPage: () => <div>TRAINING_STUDIO_PAGE_CONTENT</div> }));

// ── System ──
vi.mock("../features/organizations", () => ({ OrganizationsPage: () => <div>ORGANIZATIONS_PAGE_CONTENT</div> }));
vi.mock("../features/settings", () => ({ SettingsPage: () => <div>SETTINGS_PAGE_CONTENT</div> }));
vi.mock("../features/teams", () => ({ TeamsPage: () => <div>TEAMS_PAGE_CONTENT</div> }));
vi.mock("../features/billing", () => ({ BillingPage: () => <div>BILLING_PAGE_CONTENT</div> }));

// Unused pages (still in app, just not in sidebar nav)
vi.mock("../features/ai", () => ({ AIWorkspace: () => <div>AI_PAGE_CONTENT</div> }));
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
  beforeEach(() => {
    // Reset URL so pageFromCurrentPath() starts each test at app-builder ("/").
    window.history.replaceState(null, "", "/");
  });

  afterEach(() => {
    newProjectShouldThrow = false;
  });

  /**
   * All sidebar nav buttons — title attribute matches the i18n label.
   * Label → page content invariant: the content shown must always match
   * the button that's marked aria-current="page".
   */
  it("clicking each sidebar item renders that page and marks it active — never disagreeing", async () => {
    renderApp();
    // Default page is app-builder (path "/" → app-builder in PATH_TO_PAGE).
    await screen.findByText("APP_BUILDER_PAGE_CONTENT", {}, { timeout: 8000 });

    // [title in sidebar, expected main content] pairs — new consolidated nav
    const cases: [string, string][] = [
      ["New Project", "NEW_PROJECT_PAGE_CONTENT"],
      ["Settings",    "SETTINGS_PAGE_CONTENT"],
      ["Home",        "HOME_PAGE_CONTENT"],
    ];

    for (const [label, expectedContent] of cases) {
      const navButton = screen.getByTitle(label);
      fireEvent.click(navButton);

      // The content that actually appears must match the button that's
      // marked active — this is the exact invariant that broke before.
      await waitFor(() => expect(screen.getByText(expectedContent)).toBeInTheDocument(), { timeout: 8000 });
      expect(navButton).toHaveAttribute("aria-current", "page");
    }
  }, 60000);

  it("survives rapid sequential navigation without ending up on the wrong page", async () => {
    renderApp();
    await screen.findByText("APP_BUILDER_PAGE_CONTENT", {}, { timeout: 8000 });

    // Fire clicks back-to-back with no awaits in between — the scenario
    // that used to desync Sidebar from <main>.
    fireEvent.click(screen.getByTitle("New Project"));
    fireEvent.click(screen.getByTitle("Leads"));
    fireEvent.click(screen.getByTitle("Settings"));

    await waitFor(() => expect(screen.getByText("SETTINGS_PAGE_CONTENT")).toBeInTheDocument(), { timeout: 8000 });
    expect(screen.getByTitle("Settings")).toHaveAttribute("aria-current", "page");
    // No other page's content should be left mounted alongside it.
    expect(screen.queryByText("NEW_PROJECT_PAGE_CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("LEADS_PAGE_CONTENT")).not.toBeInTheDocument();
  }, 60000);

  it("resets ErrorBoundary when navigating away from a page that crashed", async () => {
    newProjectShouldThrow = true;
    renderApp();
    await screen.findByText("APP_BUILDER_PAGE_CONTENT", {}, { timeout: 8000 });

    fireEvent.click(screen.getByTitle("New Project"));
    await waitFor(() => expect(screen.getByText(/Error in new-project/i)).toBeInTheDocument(), { timeout: 8000 });

    // The crash must not leak into the next page's view.
    fireEvent.click(screen.getByTitle("Home"));
    await waitFor(() => expect(screen.getByText("HOME_PAGE_CONTENT")).toBeInTheDocument(), { timeout: 8000 });
    expect(screen.queryByText(/Error in new-project/i)).not.toBeInTheDocument();
  }, 60000);
});
