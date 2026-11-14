/**
 * LeadsPage — no-organization guard.
 *
 * Lead endpoints are org-scoped. A user without a selected organization must
 * see how to get one (create form when they have none) instead of an endless
 * "loading" state, and no leads request may be made without an org.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ToastCtx } from "../../../contexts/toast";

vi.mock("../../../shared/utils/api", () => {
  class APIError extends Error {}
  return { apiFetch: vi.fn(), parseJSON: vi.fn(), APIError, API: "" };
});

const createOrg = vi.fn();
let orgState = {
  loading: false,
  currentOrgId: null as string | null,
  orgs: [] as Array<{ id: string; name: string }>,
};

vi.mock("../../../contexts/OrgContext", () => ({
  useOrg: () => ({
    ...orgState,
    currentOrg: null,
    setCurrentOrgId: vi.fn(),
    refreshOrgs: vi.fn(),
    createOrg,
  }),
}));

import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { LeadsPage } from "../LeadsPage";

const mockedApiFetch = vi.mocked(apiFetch);
const mockedParseJSON = vi.mocked(parseJSON);

function renderPage() {
  return render(
    <ToastCtx.Provider value={vi.fn()}>
      <LeadsPage />
    </ToastCtx.Provider>,
  );
}

function leadRequests() {
  return mockedApiFetch.mock.calls.filter(([url]) => String(url).startsWith("/api/leads"));
}

describe("LeadsPage — no-organization guard", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedParseJSON.mockReset();
    createOrg.mockReset();
    mockedApiFetch.mockResolvedValue(new Response("", { status: 200 }));
    mockedParseJSON.mockResolvedValue({ leads: [], items: [], total: 0 });
  });

  it("offers to create an organization when the user has none", async () => {
    orgState = { loading: false, currentOrgId: null, orgs: [] };
    createOrg.mockResolvedValue({ id: "org-1" });
    renderPage();

    expect(screen.getByText("No organization selected")).toBeInTheDocument();
    expect(screen.queryByText("Loading leads…")).not.toBeInTheDocument();
    expect(leadRequests()).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("Organization name"), { target: { value: "  Acme Agency " } });
    fireEvent.click(screen.getByText("Create organization"));
    await waitFor(() => expect(createOrg).toHaveBeenCalledWith("Acme Agency"));
  });

  it("points to the Organizations page when the user has orgs but none is selected", () => {
    orgState = { loading: false, currentOrgId: null, orgs: [{ id: "org-1", name: "Acme" }] };
    renderPage();

    expect(screen.getByText("No organization selected")).toBeInTheDocument();
    expect(screen.getByText(/Organizations page/)).toBeInTheDocument();
    expect(screen.queryByText("Create organization")).not.toBeInTheDocument();
    expect(leadRequests()).toHaveLength(0);
  });

  it("does not show the no-org state while organizations are still loading", () => {
    orgState = { loading: true, currentOrgId: null, orgs: [] };
    renderPage();

    expect(screen.queryByText("No organization selected")).not.toBeInTheDocument();
    expect(screen.getByText("Loading leads…")).toBeInTheDocument();
    expect(leadRequests()).toHaveLength(0);
  });

  it("loads the org's leads once an organization is selected", async () => {
    orgState = { loading: false, currentOrgId: "org-1", orgs: [{ id: "org-1", name: "Acme" }] };
    renderPage();

    expect(screen.queryByText("No organization selected")).not.toBeInTheDocument();
    await waitFor(() => expect(leadRequests().map(([url]) => url)).toContain("/api/leads?limit=100"));
  });
});
