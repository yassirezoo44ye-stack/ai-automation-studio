import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { LegalPage } from "../LegalPage";
import { LEGAL_DOCS, legalDocFromPath, type LegalDocId } from "../content";

const langState = { lang: "en" as "en" | "ar" };
vi.mock("../../../contexts/lang", () => ({
  useLangContext: () => ({ lang: langState.lang, setLang: vi.fn(), toggleLang: vi.fn() }),
}));

describe("legal pages", () => {
  it("maps public paths to documents", () => {
    expect(legalDocFromPath("/privacy")).toBe("privacy");
    expect(legalDocFromPath("/terms/")).toBe("terms");
    expect(legalDocFromPath("/refunds")).toBe("refunds");
    expect(legalDocFromPath("/privacy-tools")).toBeNull();
    expect(legalDocFromPath("/")).toBeNull();
  });

  it("has the same sections in Arabic and English", () => {
    for (const id of ["privacy", "terms", "refunds"] as LegalDocId[]) {
      expect(LEGAL_DOCS.ar[id].sections.length).toBe(LEGAL_DOCS.en[id].sections.length);
    }
  });

  it("renders the privacy policy with links to the other policies", () => {
    langState.lang = "en";
    render(<LegalPage doc="privacy" />);
    expect(screen.getByRole("heading", { level: 1, name: "Privacy Policy" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Terms of Use" })).toHaveAttribute("href", "/terms");
    expect(screen.getByText(/Download my data/)).toBeInTheDocument();
  });

  it("renders in Arabic", () => {
    langState.lang = "ar";
    render(<LegalPage doc="terms" />);
    expect(screen.getByRole("heading", { level: 1, name: "شروط الاستخدام" })).toBeInTheDocument();
  });
});
