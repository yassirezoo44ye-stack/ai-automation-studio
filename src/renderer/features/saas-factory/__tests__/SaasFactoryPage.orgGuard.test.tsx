/**
 * SaasFactoryPage — org-context guard tests.
 *
 * Verifies three invariants introduced by the org-ready fix:
 *   1. loadProjects is NOT called while org is loading / not selected.
 *   2. loadProjects IS called once org becomes ready.
 *   3. loadProjects is re-called when the active org switches.
 */
import { render, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ── controlled orgReady state ──────────────────────────────────────────────
let orgState = { loading: true, currentOrgId: null as string | null };

vi.mock("../../../contexts/OrgContext", () => ({
  useOrg: () => ({
    loading: orgState.loading,
    currentOrgId: orgState.currentOrgId,
    currentOrg: null,
    orgs: [],
    setCurrentOrgId: vi.fn(),
    refreshOrgs: vi.fn(),
    createOrg: vi.fn(),
  }),
}));

// ── controlled loadProjects spy ────────────────────────────────────────────
const loadProjectsSpy = vi.fn().mockResolvedValue(undefined);

vi.mock("../hooks/useSaasFactory", () => ({
  useSaasFactory: () => ({
    project: null,
    projects: [],
    loading: false,
    error: null,
    submit: vi.fn(),
    resume: vi.fn(),
    remove: vi.fn(),
    loadProjects: loadProjectsSpy,
    openProject: vi.fn(),
  }),
}));

// ── shallow stubs for heavy sub-components ─────────────────────────────────
vi.mock("../components/IdeaInput", () => ({
  IdeaInput: () => <div data-testid="idea-input" />,
}));
vi.mock("../components/PipelineView", () => ({
  PipelineView: () => <div data-testid="pipeline-view" />,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string) => k,
    i18n: { language: "en" },
  }),
}));

// ── CSS imports ────────────────────────────────────────────────────────────
vi.mock("../SaasFactoryPage.css", () => ({}));

import { SaasFactoryPage } from "../SaasFactoryPage";

// ── helpers ────────────────────────────────────────────────────────────────
function setOrg(loading: boolean, id: string | null) {
  orgState = { loading, currentOrgId: id };
}

// ══════════════════════════════════════════════════════════════════════════
describe("SaasFactoryPage — org-context guard", () => {
  beforeEach(() => {
    loadProjectsSpy.mockClear();
    setOrg(true, null); // start every test in "loading, no org" state
  });

  it("does NOT call loadProjects while org is loading", () => {
    setOrg(true, null);
    render(<SaasFactoryPage />);
    expect(loadProjectsSpy).not.toHaveBeenCalled();
  });

  it("does NOT call loadProjects when loading is done but org ID is null", () => {
    setOrg(false, null);
    render(<SaasFactoryPage />);
    expect(loadProjectsSpy).not.toHaveBeenCalled();
  });

  it("calls loadProjects once org is ready on initial render", async () => {
    setOrg(false, "org-abc");
    await act(async () => { render(<SaasFactoryPage />); });
    expect(loadProjectsSpy).toHaveBeenCalledTimes(1);
  });

  it("re-calls loadProjects when currentOrgId changes (org switch)", async () => {
    setOrg(false, "org-abc");
    const { rerender } = await act(async () => ({
      ...render(<SaasFactoryPage />),
    }));
    expect(loadProjectsSpy).toHaveBeenCalledTimes(1);

    setOrg(false, "org-xyz");
    await act(async () => { rerender(<SaasFactoryPage />); });
    expect(loadProjectsSpy).toHaveBeenCalledTimes(2);
  });
});
