/**
 * HomePage — org-context guard tests for org-gated useAsyncData calls.
 *
 * Verifies three invariants:
 *   1. /api/workflows/active and /api/workflows/approvals/pending are NOT
 *      fetched while org is not ready (prevent HTTP 400).
 *   2. Both endpoints ARE fetched once org becomes ready.
 *   3. /api/stats is fetched regardless of org readiness (not org-gated).
 */
import { render, act, waitFor } from "@testing-library/react";
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

// ── apiFetch spy — records which paths were called ─────────────────────────
const apiFetchSpy = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => ({}),
  text: async () => "{}",
});

const SHAPE_BY_PATH: Record<string, unknown> = {
  "/api/projects":                      [],
  "/api/agentos/agents":                { count: 0, agents: [] },
  "/api/workflows/active":              { runs: [] },
  "/api/workflows/approvals/pending":   { pending: [] },
  "/api/stats":                         { projects: 0, agent_runs: 0, completed_runs: 0, failed_runs: 0, active_runs: 0, conversations: 0, messages: 0, success_rate: 0, failed_run_items: [], recent_activity: [] },
};

vi.mock("../../../utils/api", () => ({
  apiFetch: (...args: unknown[]) => apiFetchSpy(...args),
  parseJSON: async <T,>(_r: unknown, path: string): Promise<T> =>
    (SHAPE_BY_PATH[path] ?? {}) as T,
  APIError: class extends Error {},
}));

// ── stub all heavy context/UI deps ─────────────────────────────────────────
vi.mock("../../../contexts/app", () => ({
  useAppContext: () => ({ setPage: vi.fn(), setActiveProject: vi.fn() }),
}));
vi.mock("../../../contexts/lang", () => ({
  useLangContext: () => ({ lang: "en" }),
}));
vi.mock("../../../contexts/toast", () => ({
  useToast: () => vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts?.returnObjects ? [] : k,
    i18n: { language: "en" },
  }),
}));
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../../../shared/ui/StateViews", () => ({
  ErrorState: () => <div />,
}));
vi.mock("../../../utils/time", () => ({
  relTime: () => "just now",
}));

import { HomePage } from "../HomePage";

function setOrg(loading: boolean, id: string | null) {
  orgState = { loading, currentOrgId: id };
}

// ══════════════════════════════════════════════════════════════════════════
describe("HomePage — org-context guard on org-gated queries", () => {
  beforeEach(() => {
    apiFetchSpy.mockClear();
    setOrg(true, null);
  });

  it("does NOT fetch org-gated endpoints while org is loading", async () => {
    setOrg(true, null);
    await act(async () => { render(<HomePage />); });

    const calledPaths = apiFetchSpy.mock.calls.map(c => c[0] as string);
    expect(calledPaths).not.toContain("/api/workflows/active");
    expect(calledPaths).not.toContain("/api/workflows/approvals/pending");
  });

  it("does NOT fetch org-gated endpoints when loading done but no org ID", async () => {
    setOrg(false, null);
    await act(async () => { render(<HomePage />); });

    const calledPaths = apiFetchSpy.mock.calls.map(c => c[0] as string);
    expect(calledPaths).not.toContain("/api/workflows/active");
    expect(calledPaths).not.toContain("/api/workflows/approvals/pending");
  });

  it("fetches /api/stats even when org is not ready", async () => {
    setOrg(true, null);
    await act(async () => { render(<HomePage />); });

    await waitFor(() => {
      const calledPaths = apiFetchSpy.mock.calls.map(c => c[0] as string);
      expect(calledPaths).toContain("/api/stats");
    });
  });

  it("fetches org-gated endpoints once org becomes ready", async () => {
    setOrg(false, "org-abc");
    await act(async () => { render(<HomePage />); });

    await waitFor(() => {
      const calledPaths = apiFetchSpy.mock.calls.map(c => c[0] as string);
      expect(calledPaths).toContain("/api/workflows/active");
      expect(calledPaths).toContain("/api/workflows/approvals/pending");
    });
  });

  it("re-fetches org-gated endpoints when org switches", async () => {
    setOrg(false, "org-abc");
    const { rerender } = await act(async () => ({
      ...render(<HomePage />),
    }));

    const countBefore = apiFetchSpy.mock.calls.filter(
      c => c[0] === "/api/workflows/active",
    ).length;

    setOrg(false, "org-xyz");
    await act(async () => { rerender(<HomePage />); });

    await waitFor(() => {
      const countAfter = apiFetchSpy.mock.calls.filter(
        c => c[0] === "/api/workflows/active",
      ).length;
      expect(countAfter).toBeGreaterThan(countBefore);
    });
  });
});
