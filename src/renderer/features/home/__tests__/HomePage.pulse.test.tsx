/**
 * HomePage — "Ask Flow" hands a question to My AI Assistant, and the business
 * pulse shows lead tiers for the selected organization only.
 */
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

let orgState = { loading: false, currentOrgId: "org-1" as string | null };
vi.mock("../../../contexts/OrgContext", () => ({
  useOrg: () => ({ ...orgState, currentOrg: null, orgs: [], setCurrentOrgId: vi.fn(), refreshOrgs: vi.fn(), createOrg: vi.fn() }),
}));

const LEADS = {
  leads: [
    { id: "a", name: "Sara", status: "qualified", ai_tier: "hot", ai_score: 9 },
    { id: "b", name: "Omar", status: "new", ai_tier: "warm", ai_score: 5 },
    { id: "c", name: "Old Win", status: "won", ai_tier: "hot", ai_score: 9 },
  ],
};
const apiFetchSpy = vi.fn().mockResolvedValue({ ok: true });
vi.mock("../../../utils/api", () => ({
  apiFetch: (...args: unknown[]) => apiFetchSpy(...args),
  parseJSON: async (_r: unknown, path: string) => (path.startsWith("/api/leads") ? LEADS : path === "/api/projects" ? [] : {}),
  APIError: class extends Error {},
}));
const setPage = vi.fn();
vi.mock("../../../contexts/app", () => ({ useAppContext: () => ({ setPage, setActiveProject: vi.fn() }) }));
vi.mock("../../../contexts/lang", () => ({ useLangContext: () => ({ lang: "en" }) }));
vi.mock("../../../contexts/toast", () => ({ useToast: () => vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts?.returnObjects ? (k === "cc.ask.suggestions" ? ["Plan my week"] : []) : opts?.names ? `${k}:${opts.names}` : k,
    i18n: { language: "en" },
  }),
}));
vi.mock("framer-motion", () => ({
  motion: { div: ({ children }: { children: React.ReactNode }) => <div>{children}</div> },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../../../shared/ui/StateViews", () => ({ ErrorState: () => <div /> }));
vi.mock("../../../utils/time", () => ({ relTime: () => "just now" }));

import { HomePage } from "../HomePage";

beforeEach(() => {
  orgState = { loading: false, currentOrgId: "org-1" };
  apiFetchSpy.mockClear();
  setPage.mockClear();
  sessionStorage.clear();
});

describe("HomePage — Ask Flow and business pulse", () => {
  it("hands the typed question to My AI Assistant", async () => {
    await act(async () => { render(<HomePage />); });
    fireEvent.change(screen.getByLabelText("cc.ask.label"), { target: { value: "  Write a follow-up for Sara  " } });
    fireEvent.click(screen.getByRole("button", { name: "cc.ask.submit" }));
    expect(sessionStorage.getItem("flow_assistant_prompt")).toBe("Write a follow-up for Sara");
    expect(setPage).toHaveBeenCalledWith("ai");
  });

  it("a suggestion chip asks directly", async () => {
    await act(async () => { render(<HomePage />); });
    fireEvent.click(screen.getByRole("button", { name: "Plan my week" }));
    expect(sessionStorage.getItem("flow_assistant_prompt")).toBe("Plan my week");
    expect(setPage).toHaveBeenCalledWith("ai");
  });

  it("counts open leads by tier and names the hot ones", async () => {
    await act(async () => { render(<HomePage />); });
    await waitFor(() => expect(screen.getByText("cc.pulse.hotNow:Sara")).toBeInTheDocument());
    const hot = screen.getByText("cc.pulse.hot").closest("div");
    expect(hot).toHaveTextContent("1");   // the won hot lead is not open
    expect(screen.getByText("cc.pulse.open_").closest("div")).toHaveTextContent("2");
    fireEvent.click(screen.getByRole("button", { name: /cc\.pulse\.open →/ }));
    expect(setPage).toHaveBeenCalledWith("leads");
  });

  it("does not request leads without an organization", async () => {
    orgState = { loading: false, currentOrgId: null };
    await act(async () => { render(<HomePage />); });
    expect(screen.getByText("cc.pulse.noOrg")).toBeInTheDocument();
    expect(apiFetchSpy.mock.calls.some(([p]) => String(p).startsWith("/api/leads"))).toBe(false);
  });
});
