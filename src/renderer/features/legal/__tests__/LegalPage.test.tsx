import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LangContext, type Lang } from "../../../contexts/lang";
import { LegalPage } from "../LegalPage";
import { getLegalContent } from "../legalContent";
import { legalDocForPath } from "../legalRoutes";

function renderIn(lang: Lang, doc: "privacy" | "terms") {
  return render(
    <LangContext.Provider value={{ lang, setLang: () => {}, toggleLang: () => {} }}>
      <LegalPage doc={doc} />
    </LangContext.Provider>,
  );
}

describe("legalDocForPath", () => {
  it("maps legal paths, tolerating a trailing slash", () => {
    expect(legalDocForPath("/privacy")).toBe("privacy");
    expect(legalDocForPath("/terms/")).toBe("terms");
    expect(legalDocForPath("/")).toBeNull();
    expect(legalDocForPath("/privacy-settings")).toBeNull();
  });
});

describe("LegalPage", () => {
  it("renders the English privacy policy with a link to the terms", () => {
    renderIn("en", "privacy");
    expect(screen.getByRole("heading", { level: 1, name: "Privacy Policy" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Terms of Use" })).toHaveAttribute("href", "/terms");
  });

  it("renders the Arabic terms right-to-left", () => {
    const { container } = renderIn("ar", "terms");
    expect(screen.getByRole("heading", { level: 1, name: "شروط الاستخدام" })).toBeInTheDocument();
    expect(container.firstElementChild).toHaveAttribute("dir", "rtl");
  });

  it("keeps both languages structurally identical", () => {
    for (const doc of ["privacy", "terms"] as const) {
      const en = getLegalContent(doc, "en");
      const ar = getLegalContent(doc, "ar");
      expect(ar.sections.length).toBe(en.sections.length);
      en.sections.forEach((s, i) => {
        expect(ar.sections[i].bullets?.length).toBe(s.bullets?.length);
        expect(ar.sections[i].paragraphs?.length).toBe(s.paragraphs?.length);
        expect(ar.sections[i].after?.length).toBe(s.after?.length);
      });
    }
  });
});
