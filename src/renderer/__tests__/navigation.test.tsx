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
 * PageTransition/ErrorBoundary/Suspense wiring — only the 16 feature pages
 * and the auth/org contexts are stubbed, since their own data-fetching is
 * not what's under test here.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AppProvider } from "../contexts/AppContext";
import { AppLayout } from "../components/layout/AppLayout";

vi.mock("../contexts/AuthContext", () => ({
  useAuth: () => ({ user: { email: "qa@example.com" }, logout: vi.fn() }),
}));
vi.mock("../contexts/OrgContext", () => ({
  useOrg: () => ({ orgs: [], currentOrgId: null, setCurrentOrgId: vi.fn() }),
}));

// Toggled per-test to exercise the ErrorBoundary-reset regression guard.
let aiShouldThrow = false;

vi.mock("../features/home", () => ({ HomePage: () => <div>HOME_PAGE_CONTENT</div> }));
vi.mock("../features/ai", () => ({
  AIWorkspace: () => {
    if (aiShouldThrow) throw new Error("Simulated AI page crash");
    return <div>AI_PAGE_CONTENT</div>;
  },
}));
vi.mock("../features/dev", () => ({ DevWorkspace: () => <div>DEV_PAGE_CONTENT</div> }));
vi.mock("../features/design-studio", () => ({ DesignStudio: () => <div>DESIGN_PAGE_CONTENT</div> }));
vi.mock("../features/automation/AutomationPage", () => ({ AutomationPage: () => <div>AUTOMATION_PAGE_CONTENT</div> }));
vi.mock("../features/agentos", () => ({ AgentOSPage: () => <div>AGENTOS_PAGE_CONTENT</div> }));
vi.mock("../features/marketplace", () => ({ MarketplacePage: () => <div>MARKETPLACE_PAGE_CONTENT</div> }));
vi.mock("../features/organizations", () => ({ OrganizationsPage: () => <div>ORGANIZATIONS_PAGE_CONTENT</div> }));
vi.mock("../features/teams", () => ({ TeamsPage: () => <div>TEAMS_PAGE_CONTENT</div> }));
vi.mock("../features/billing", () => ({ BillingPage: () => <div>BILLING_PAGE_CONTENT</div> }));
vi.mock("../features/plugins", () => ({ PluginsPage: () => <div>PLUGINS_PAGE_CONTENT</div> }));
vi.mock("../features/sandbox", () => ({ SandboxPage: () => <div>SANDBOX_PAGE_CONTENT</div> }));
vi.mock("../features/ai-routing", () => ({ AIRoutingPage: () => <div>AI_ROUTING_PAGE_CONTENT</div> }));
vi.mock("../features/observability", () => ({ ObservabilityPage: () => <div>OBSERVABILITY_PAGE_CONTENT</div> }));
vi.mock("../features/social", () => ({ SocialPage: () => <div>SOCIAL_PAGE_CONTENT</div> }));
vi.mock("../features/settings", () => ({ SettingsPage: () => <div>SETTINGS_PAGE_CONTENT</div> }));

function renderApp() {
  return render(
    <AppProvider>
      <AppLayout />
    </AppProvider>,
  );
}

describe("navigation", () => {
  it("clicking each sidebar item renders that page and marks it active — never disagreeing", async () => {
    renderApp();
    await screen.findByText("HOME_PAGE_CONTENT");

    const cases: [string, string][] = [
      ["AI", "AI_PAGE_CONTENT"],
      ["Dev", "DEV_PAGE_CONTENT"],
      ["Design", "DESIGN_PAGE_CONTENT"],
      ["Workflows", "AUTOMATION_PAGE_CONTENT"],
      ["AgentOS", "AGENTOS_PAGE_CONTENT"],
      ["Marketplace", "MARKETPLACE_PAGE_CONTENT"],
      ["Plugins", "PLUGINS_PAGE_CONTENT"],
      ["Sandbox", "SANDBOX_PAGE_CONTENT"],
      ["AI Routing", "AI_ROUTING_PAGE_CONTENT"],
      ["Observability", "OBSERVABILITY_PAGE_CONTENT"],
      ["Organizations", "ORGANIZATIONS_PAGE_CONTENT"],
      ["Teams", "TEAMS_PAGE_CONTENT"],
      ["Billing", "BILLING_PAGE_CONTENT"],
      ["Social", "SOCIAL_PAGE_CONTENT"],
      ["Settings", "SETTINGS_PAGE_CONTENT"],
      ["Home", "HOME_PAGE_CONTENT"],
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
    fireEvent.click(screen.getByTitle("AI"));
    fireEvent.click(screen.getByTitle("Dev"));
    fireEvent.click(screen.getByTitle("Design"));
    fireEvent.click(screen.getByTitle("Marketplace"));

    await waitFor(() => expect(screen.getByText("MARKETPLACE_PAGE_CONTENT")).toBeInTheDocument());
    expect(screen.getByTitle("Marketplace")).toHaveAttribute("aria-current", "page");
    // No other page's content should be left mounted alongside it.
    expect(screen.queryByText("DESIGN_PAGE_CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("DEV_PAGE_CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("AI_PAGE_CONTENT")).not.toBeInTheDocument();
  });

  it("resets ErrorBoundary when navigating away from a page that crashed", async () => {
    aiShouldThrow = true;
    renderApp();
    await screen.findByText("HOME_PAGE_CONTENT");

    fireEvent.click(screen.getByTitle("AI"));
    await waitFor(() => expect(screen.getByText(/Error in ai/i)).toBeInTheDocument());

    // The crash must not leak into the next page's view.
    fireEvent.click(screen.getByTitle("Home"));
    await waitFor(() => expect(screen.getByText("HOME_PAGE_CONTENT")).toBeInTheDocument());
    expect(screen.queryByText(/Error in ai/i)).not.toBeInTheDocument();

    aiShouldThrow = false;
  });
});
