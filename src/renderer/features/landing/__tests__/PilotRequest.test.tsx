import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import i18n from "../../../i18n";
import en from "../../../locales/en/landing.json";
import ar from "../../../locales/ar/landing.json";

const langState = { lang: "en" as "en" | "ar" };
vi.mock("../../../contexts/lang", () => ({
  useLangContext: () => ({ lang: langState.lang, setLang: vi.fn(), toggleLang: vi.fn() }),
}));
vi.mock("../../../lib/utm", () => ({ captureUtm: vi.fn(), trackEvent: vi.fn() }));

import { PilotRequestSection } from "../LandingPage";

function fill() {
  fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Sara Ali" } });
  fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "sara@agency.example" } });
  fireEvent.change(screen.getByLabelText("Agency or company"), { target: { value: "Bright Agency" } });
  fireEvent.change(screen.getByLabelText("Team size"), { target: { value: "6-20" } });
  fireEvent.change(screen.getByLabelText("Which repetitive task would you automate first?"), {
    target: { value: "Weekly client reports take six hours." },
  });
}

describe("paid pilot request form", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    langState.lang = "en";
    void i18n.changeLanguage("en");
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("posts the request and confirms it was received", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ status: "received" }), { status: 202 }));
    render(<PilotRequestSection />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Request a pilot" }));

    await screen.findByText("Request received.");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/pilot-requests$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      name: "Sara Ali",
      email: "sara@agency.example",
      company: "Bright Agency",
      team_size: "6-20",
      task: "Weekly client reports take six hours.",
      lang: "en",
      website: "",
    });
  });

  it("does not claim success when the server cannot take requests", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 503 }));
    render(<PilotRequestSection />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Request a pilot" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not send your request");
    expect(screen.queryByText("Request received.")).not.toBeInTheDocument();
    // The form stays filled so nothing typed is lost.
    expect(screen.getByLabelText("Agency or company")).toHaveValue("Bright Agency");
  });

  it("explains a rate limit", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 429 }));
    render(<PilotRequestSection />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Request a pilot" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests");
  });

  it("asks for more detail before sending a too-short task", async () => {
    render(<PilotRequestSection />);
    fill();
    fireEvent.change(screen.getByLabelText("Which repetitive task would you automate first?"), {
      target: { value: "reports" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Request a pilot" }).closest("form")!);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("sentence or two"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the honeypot out of reach of keyboard and screen readers", () => {
    const { container } = render(<PilotRequestSection />);
    const hp = container.querySelector("input[name=website]")!;
    expect(hp).toHaveAttribute("tabindex", "-1");
    expect(hp).toHaveAttribute("aria-hidden", "true");
  });

  it("has the same pilot and pricing keys in Arabic and English", () => {
    const keys = (o: object, p = ""): string[] =>
      Object.entries(o).flatMap(([k, v]) =>
        v && typeof v === "object" && !Array.isArray(v) ? keys(v, `${p}${k}.`) : [`${p}${k}`]);
    expect(keys(ar.pilot)).toEqual(keys(en.pilot));
    expect(keys(ar.pricing)).toEqual(keys(en.pricing));
    expect(en.pricing.plans).not.toHaveProperty("pro");
  });
});
