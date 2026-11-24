import { useEffect } from "react";

/**
 * Per-page search and share metadata for the public (signed-out) pages.
 *
 * index.html carries English defaults for crawlers and link previews that do
 * not run JavaScript. Google renders the page, so this hook replaces the
 * title, description, canonical URL, language alternates and Open Graph tags
 * with the ones for the page and language actually shown.
 */
export interface PageMeta {
  title: string;
  description: string;
  /** Path of this page in this language, e.g. "/ar". Used for canonical and og:url. */
  path: string;
  /** "ar" or "en": sets og:locale. */
  lang: string;
  /** Language alternates: hreflang -> path. Include "x-default". */
  alternates?: Record<string, string>;
}

function upsertMeta(attr: "name" | "property", key: string, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.content = content;
}

function upsertLink(rel: string, href: string, hreflang?: string) {
  const selector = hreflang ? `link[rel="${rel}"][hreflang="${hreflang}"]` : `link[rel="${rel}"]:not([hreflang])`;
  let el = document.head.querySelector<HTMLLinkElement>(selector);
  if (!el) {
    el = document.createElement("link");
    el.rel = rel;
    if (hreflang) el.hreflang = hreflang;
    document.head.appendChild(el);
  }
  el.href = href;
}

export function applyPageMeta(meta: PageMeta, origin = window.location.origin) {
  const url = origin + meta.path;
  document.title = meta.title;
  upsertMeta("name", "description", meta.description);
  upsertMeta("property", "og:title", meta.title);
  upsertMeta("property", "og:description", meta.description);
  upsertMeta("property", "og:url", url);
  upsertMeta("property", "og:locale", meta.lang === "ar" ? "ar_AR" : "en_US");
  upsertMeta("name", "twitter:title", meta.title);
  upsertMeta("name", "twitter:description", meta.description);
  upsertLink("canonical", url);
  document.head.querySelectorAll('link[rel="alternate"][hreflang]').forEach(el => el.remove());
  for (const [hreflang, path] of Object.entries(meta.alternates ?? {})) {
    upsertLink("alternate", origin + path, hreflang);
  }
}

export function usePageMeta(meta: PageMeta) {
  const { title, description, path, lang } = meta;
  const alternates = JSON.stringify(meta.alternates ?? {});
  useEffect(() => {
    applyPageMeta({ title, description, path, lang, alternates: JSON.parse(alternates) as Record<string, string> });
  }, [title, description, path, lang, alternates]);
}

/** The landing page's language URLs. "/" stays the default for visitors who pick no language. */
export const LANDING_ALTERNATES = { en: "/en", ar: "/ar", "x-default": "/" };

/** "/ar" or "/en" when the URL names a language, otherwise null. */
export function langFromPath(pathname: string): "ar" | "en" | null {
  const m = /^\/(ar|en)\/?$/.exec(pathname);
  return m ? (m[1] as "ar" | "en") : null;
}
