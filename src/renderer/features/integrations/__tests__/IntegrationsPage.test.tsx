import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { IntegrationsPage } from "../IntegrationsPage";

let mockOrgId: string | null = "org-1";
vi.mock("../../../contexts/OrgContext", () => ({
  useOrg: () => ({ currentOrgId: mockOrgId, orgs: mockOrgId ? [{ id: "org-1", name: "Acme" }] : [] }),
}));

const toastSpy = vi.fn();
vi.mock("../../../contexts/toast", () => ({ useToast: () => toastSpy }));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const PROVIDERS = {
  providers: [
    {
      provider_id: "webhook-relay", display_name: "Webhook Relay",
      provider_type: "custom",
      capabilities: { sync: true, webhooks: true, background_jobs: true, real_time: false },
      scopes: [{ id: "receive", label: "Receive relayed webhook events", sensitive: false }],
    },
  ],
};

describe("IntegrationsPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    toastSpy.mockClear();
    mockOrgId = "org-1";
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads and renders providers with a Connect action when not connected", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/providers")) return Promise.resolve(jsonResponse(PROVIDERS));
      return Promise.resolve(jsonResponse({ integrations: [] }));
    });

    render(<IntegrationsPage />);

    expect(await screen.findByText("Webhook Relay")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disconnect" })).not.toBeInTheDocument();
  });

  it("shows connected status + Sync/Disconnect actions for an already-connected provider", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/providers")) return Promise.resolve(jsonResponse(PROVIDERS));
      return Promise.resolve(jsonResponse({
        integrations: [{
          provider_id: "webhook-relay", provider_type: "custom", status: "connected",
          granted_scopes: ["receive"], connected_at: "2026-01-01T00:00:00Z", last_sync_at: null,
        }],
      }));
    });

    render(<IntegrationsPage />);

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconfigure" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync now" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument();
  });

  it("shows an empty state when no providers are registered", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/providers")) return Promise.resolve(jsonResponse({ providers: [] }));
      return Promise.resolve(jsonResponse({ integrations: [] }));
    });

    render(<IntegrationsPage />);
    expect(await screen.findByText("No integration providers available")).toBeInTheDocument();
  });

  it("shows an error state with Retry when the load fails, and Retry re-fetches", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({}, 500));
    fetchMock.mockResolvedValueOnce(jsonResponse({ integrations: [] }));
    fetchMock.mockResolvedValueOnce(jsonResponse(PROVIDERS));
    fetchMock.mockResolvedValueOnce(jsonResponse({ integrations: [] }));

    render(<IntegrationsPage />);

    expect(await screen.findByText("Could not load integrations")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("Webhook Relay")).toBeInTheDocument());
  });

  it("submits the generic secret key/value form to POST /connect and never sends an empty key", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/providers")) return Promise.resolve(jsonResponse(PROVIDERS));
      if (init?.method === "POST" && url.endsWith("/connect")) return Promise.resolve(jsonResponse({ status: "connected" }, 201));
      return Promise.resolve(jsonResponse({ integrations: [] }));
    });

    render(<IntegrationsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));

    fireEvent.change(screen.getByPlaceholderText("Key (e.g. api_key)"), { target: { value: "webhook_secret" } });
    fireEvent.change(screen.getByPlaceholderText("Value"), { target: { value: "s3cr3t" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(toastSpy).toHaveBeenCalledWith("Integration connected", "ok"));
    const connectCall = fetchMock.mock.calls.find(([url]) => (url as string).endsWith("/connect"));
    expect(connectCall).toBeDefined();
    const body = JSON.parse((connectCall![1] as RequestInit).body as string);
    expect(body).toEqual({ secrets: { webhook_secret: "s3cr3t" }, granted_scopes: [] });
  });

  it("shows the no-organization empty state and never calls the API when no org is selected", async () => {
    mockOrgId = null;
    render(<IntegrationsPage />);
    expect(await screen.findByText("No organization selected")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});
