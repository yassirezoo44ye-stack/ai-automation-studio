import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { SettingsPage } from "../SettingsPage";

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock("../../../utils/api", () => {
  class APIError extends Error {
    constructor(
      message: string,
      public readonly details: { url: string; status: number; contentType: string },
    ) {
      super(message);
      this.name = "APIError";
    }
  }
  return { apiFetch: vi.fn(), parseJSON: vi.fn(), APIError, API: "" };
});

vi.mock("../../../contexts/OrgContext", () => ({
  useOrg: vi.fn(() => ({ currentOrgId: "org-1", orgs: [], loading: false })),
}));

vi.mock("../../../contexts/app", () => ({
  useAppContext: vi.fn(() => ({
    theme: "dark", setTheme: vi.fn(),
    setSidebarCollapsed: vi.fn(), page: "settings", setPage: vi.fn(),
    sidebarCollapsed: false,
  })),
}));

vi.mock("../../../contexts/lang", () => ({
  useLangContext: vi.fn(() => ({ lang: "en", setLang: vi.fn() })),
}));

import { apiFetch, parseJSON, APIError } from "../../../utils/api";
const mockedApiFetch = vi.mocked(apiFetch);
const mockedParseJSON = vi.mocked(parseJSON);

// ── Helpers ───────────────────────────────────────────────────────────────────

function fakeRes(status = 200) {
  // jsdom's Response only accepts 200-599; map 204 to 200 for the mock
  const safeStatus = status === 204 ? 200 : status;
  return new Response("", { status: safeStatus });
}

function makeKey(overrides: Partial<{ key_id: string; name: string }> = {}) {
  return {
    key_id: "key-1",
    name: "Lead Capture Form",
    scopes: ["read", "write"],
    organization_id: "org-1",
    expires_at: null,
    ...overrides,
  };
}

// SettingsPage's mount effects call fetch(/health) and apiFetch for /api/stats, /api/runtimes.
// parseJSON is called for all three, so we must account for all three slots.
function setupSystemEffects() {
  // /health uses global fetch (mocked in beforeEach) but still calls parseJSON
  mockedParseJSON.mockResolvedValueOnce({ status: "ok", db: "ok", pg_version: "14" });
  // /api/stats
  mockedApiFetch.mockResolvedValueOnce(fakeRes(200));
  mockedParseJSON.mockResolvedValueOnce({ projects: 0, conversations: 0, messages: 0, agent_runs: 0, success_rate: 100 });
  // /api/runtimes
  mockedApiFetch.mockResolvedValueOnce(fakeRes(200));
  mockedParseJSON.mockResolvedValueOnce({ runtimes: {} });
}

function setupEmptyList() {
  setupSystemEffects();
  mockedApiFetch.mockResolvedValueOnce(fakeRes(200));
  mockedParseJSON.mockResolvedValueOnce({ keys: [] });
}

function setupExistingKeys(keys = [makeKey()]) {
  setupSystemEffects();
  mockedApiFetch.mockResolvedValueOnce(fakeRes(200));
  mockedParseJSON.mockResolvedValueOnce({ keys });
}

async function openApiKeysTab() {
  render(<SettingsPage />);
  await waitFor(() => screen.getByText("API Keys"));
  fireEvent.click(screen.getByText("API Keys"));
}

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  // fetch (for /health) is a browser global — stub it to avoid errors
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok", db: "ok", pg_version: "14" }), { status: 200 })));
});

describe("ApiKeysTab — renders", () => {
  it("renders API Keys section when tab is selected", async () => {
    setupEmptyList();
    await openApiKeysTab();
    expect(screen.getByText("Create Org API Key")).toBeInTheDocument();
    expect(screen.getByText("Existing Keys")).toBeInTheDocument();
  });

  it("renders Key Name input and Create Key button", async () => {
    setupEmptyList();
    await openApiKeysTab();
    expect(screen.getByLabelText("Key Name")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create key/i })).toBeInTheDocument();
  });
});

describe("ApiKeysTab — load existing keys", () => {
  it("loads org-scoped keys via GET /api/orgs/{org_id}/api-keys", async () => {
    setupExistingKeys();
    await openApiKeysTab();

    await waitFor(() => {
      const call = mockedApiFetch.mock.calls.find(
        ([path]) => (path as string).includes("/api/orgs/org-1/api-keys"),
      );
      expect(call).toBeDefined();
    });
  });

  it("displays existing key names without raw key values", async () => {
    setupExistingKeys([makeKey({ name: "My Form Key" })]);
    await openApiKeysTab();
    await waitFor(() => expect(screen.getByText("My Form Key")).toBeInTheDocument());
    // raw key must NOT appear in the list
    expect(screen.queryByText(/^ax_/)).not.toBeInTheDocument();
  });

  it("does NOT call personal /api/keys endpoint", async () => {
    setupEmptyList();
    await openApiKeysTab();
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled());
    const personalCall = mockedApiFetch.mock.calls.find(
      ([path]) => (path as string) === "/api/keys",
    );
    expect(personalCall).toBeUndefined();
  });
});

describe("ApiKeysTab — create key", () => {
  it("creates org-scoped key via POST /api/orgs/{org_id}/api-keys", async () => {
    setupEmptyList();
    await openApiKeysTab();
    await waitFor(() => screen.getByLabelText("Key Name"));

    const created = { api_key: "ax_live_abc123", key_id: "new-1", name: "Test", scopes: ["read", "write"] };
    mockedApiFetch.mockResolvedValueOnce(fakeRes(201));
    mockedParseJSON.mockResolvedValueOnce(created);
    // reload after creation
    mockedApiFetch.mockResolvedValueOnce(fakeRes(200));
    mockedParseJSON.mockResolvedValueOnce({ keys: [makeKey({ key_id: "new-1", name: "Test" })] });

    fireEvent.change(screen.getByLabelText("Key Name"), { target: { value: "Test" } });
    fireEvent.click(screen.getByRole("button", { name: /create key/i }));

    await waitFor(() => {
      const postCall = mockedApiFetch.mock.calls.find(
        ([path, init]) =>
          (path as string).includes("/api/orgs/org-1/api-keys") &&
          (init as RequestInit)?.method === "POST",
      );
      expect(postCall).toBeDefined();
    });
  });

  it("shows raw key after creation with Copy button", async () => {
    setupEmptyList();
    await openApiKeysTab();
    await waitFor(() => screen.getByLabelText("Key Name"));

    const created = { api_key: "ax_live_showall", key_id: "new-2", name: "ShowKey", scopes: ["read", "write"] };
    mockedApiFetch.mockResolvedValueOnce(fakeRes(201));
    mockedParseJSON.mockResolvedValueOnce(created);
    mockedApiFetch.mockResolvedValueOnce(fakeRes(200));
    mockedParseJSON.mockResolvedValueOnce({ keys: [] });

    fireEvent.change(screen.getByLabelText("Key Name"), { target: { value: "ShowKey" } });
    fireEvent.click(screen.getByRole("button", { name: /create key/i }));

    await waitFor(() => expect(screen.getByText("ax_live_showall")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("raw key does NOT appear in existing-key list rows", async () => {
    setupExistingKeys([makeKey({ name: "Existing" })]);
    await openApiKeysTab();
    await waitFor(() => screen.getByText("Existing"));

    const rows = screen.getAllByRole("button", { name: /revoke/i });
    // Only Revoke buttons — no raw key codes in the list section
    expect(rows.length).toBeGreaterThan(0);
    expect(screen.queryByText(/^ax_/)).not.toBeInTheDocument();
  });

  it("shows 403 error inline without success", async () => {
    setupEmptyList();
    await openApiKeysTab();
    await waitFor(() => screen.getByLabelText("Key Name"));

    mockedApiFetch.mockResolvedValueOnce(fakeRes(201));
    mockedParseJSON.mockRejectedValueOnce(
      new APIError("Forbidden", { url: "/api/orgs/org-1/api-keys", status: 403, contentType: "application/json" }),
    );

    fireEvent.change(screen.getByLabelText("Key Name"), { target: { value: "Blocked" } });
    fireEvent.click(screen.getByRole("button", { name: /create key/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
    expect(screen.getByRole("alert").textContent).toMatch(/owners/i);
    expect(screen.queryByText(/create org api key/i)).not.toBeUndefined();
    // created banner should NOT appear
    expect(screen.queryByText(/copy it now/i)).not.toBeInTheDocument();
  });

  it("shows error on API failure without success", async () => {
    setupEmptyList();
    await openApiKeysTab();
    await waitFor(() => screen.getByLabelText("Key Name"));

    mockedApiFetch.mockRejectedValueOnce(new Error("network"));

    fireEvent.change(screen.getByLabelText("Key Name"), { target: { value: "Fail" } });
    fireEvent.click(screen.getByRole("button", { name: /create key/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText(/copy it now/i)).not.toBeInTheDocument();
  });
});

describe("ApiKeysTab — revoke key", () => {
  it("revokes key via DELETE /api/orgs/{org_id}/api-keys/{key_id}", async () => {
    setupExistingKeys([makeKey({ key_id: "key-99" })]);
    await openApiKeysTab();
    await waitFor(() => screen.getByRole("button", { name: /revoke/i }));

    mockedApiFetch.mockResolvedValueOnce(fakeRes(204));

    fireEvent.click(screen.getByRole("button", { name: /revoke/i }));

    await waitFor(() => {
      const deleteCall = mockedApiFetch.mock.calls.find(
        ([path, init]) =>
          (path as string).includes("/api/orgs/org-1/api-keys/key-99") &&
          (init as RequestInit)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
    });
  });
});

describe("ApiKeysTab — i18n", () => {
  it("renders English keys", async () => {
    setupEmptyList();
    await openApiKeysTab();
    expect(screen.getByText("Create Org API Key")).toBeInTheDocument();
  });
});
