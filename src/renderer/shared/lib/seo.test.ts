import { afterEach, describe, expect, it } from "vitest";
import { applyPageMeta, langFromPath, LANDING_ALTERNATES } from "./seo";

const head = () => document.head;
const meta = (sel: string) => head().querySelector<HTMLMetaElement>(sel)?.content;

describe("langFromPath", () => {
  it("reads /ar and /en only", () => {
    expect(langFromPath("/ar")).toBe("ar");
    expect(langFromPath("/en/")).toBe("en");
    expect(langFromPath("/")).toBeNull();
    expect(langFromPath("/arabic")).toBeNull();
    expect(langFromPath("/ar/settings")).toBeNull();
  });
});

describe("applyPageMeta", () => {
  afterEach(() => { head().innerHTML = ""; });

  it("sets title, description, canonical, Open Graph and language alternates", () => {
    applyPageMeta({ title: "T", description: "D", path: "/ar", lang: "ar", alternates: LANDING_ALTERNATES }, "https://flow.test");
    expect(document.title).toBe("T");
    expect(meta('meta[name="description"]')).toBe("D");
    expect(meta('meta[property="og:url"]')).toBe("https://flow.test/ar");
    expect(meta('meta[property="og:locale"]')).toBe("ar_AR");
    expect(head().querySelector<HTMLLinkElement>('link[rel="canonical"]')?.href).toBe("https://flow.test/ar");
    const alts = [...head().querySelectorAll<HTMLLinkElement>('link[rel="alternate"]')].map(l => `${l.hreflang} ${l.href}`);
    expect(alts.sort()).toEqual(["ar https://flow.test/ar", "en https://flow.test/en", "x-default https://flow.test/"]);
  });

  it("updates tags in place and drops alternates a page does not have", () => {
    applyPageMeta({ title: "A", description: "a", path: "/en", lang: "en", alternates: LANDING_ALTERNATES }, "https://flow.test");
    applyPageMeta({ title: "B", description: "b", path: "/study-library", lang: "ar" }, "https://flow.test");
    expect(head().querySelectorAll('meta[name="description"]')).toHaveLength(1);
    expect(head().querySelectorAll('link[rel="canonical"]')).toHaveLength(1);
    expect(head().querySelectorAll('link[rel="alternate"]')).toHaveLength(0);
    expect(meta('meta[property="og:title"]')).toBe("B");
  });
});
