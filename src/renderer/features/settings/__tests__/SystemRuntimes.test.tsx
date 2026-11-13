/**
 * Settings → System: a build tool missing from the cloud server (npm on the
 * Python-only production image) reads as "Not on this server" with an
 * explanation, not as a failure.
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SettingsPage } from "../SettingsPage";

vi.mock("../../../utils/api", () => ({ apiFetch: vi.fn(), parseJSON: vi.fn(), APIError: class extends Error {}, API: "" }));
vi.mock("../../../contexts/OrgContext", () => ({ useOrg: vi.fn(() => ({ currentOrgId: "org-1", orgs: [], loading: false })) }));
vi.mock("../../../contexts/app", () => ({
  useAppContext: vi.fn(() => ({ theme: "dark", setTheme: vi.fn(), setSidebarCollapsed: vi.fn(), page: "settings", setPage: vi.fn(), sidebarCollapsed: false })),
}));
vi.mock("../../../contexts/lang", () => ({ useLangContext: vi.fn(() => ({ lang: "en", setLang: vi.fn() })) }));

import { apiFetch, parseJSON } from "../../../utils/api";

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
  vi.mocked(apiFetch).mockResolvedValue(new Response("", { status: 200 }));
  vi.mocked(parseJSON).mockImplementation(async (_res, endpoint) => {
    if (endpoint === "/api/runtimes") {
      return { runtimes: { python3: { available: true, version: "3.12.4" }, npm: { available: false, version: null } } } as never;
    }
    if (endpoint === "/health") return { status: "ok", db: "ok" } as never;
    return {} as never;
  });
});

describe("Settings → System runtimes", () => {
  it("labels a missing tool as not on this server and explains it", async () => {
    render(<SettingsPage />);
    expect(await screen.findByText("Not on this server")).toBeInTheDocument();
    expect(screen.getByText("3.12.4")).toBeInTheDocument();
    expect(screen.queryByText("not found")).not.toBeInTheDocument();
    expect(screen.getByText(/only needed to build desktop or Android app exports/)).toBeInTheDocument();
  });
});
