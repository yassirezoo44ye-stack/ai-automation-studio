// Tiny route helper kept apart from legalContent.ts so the long legal text
// stays in the lazily loaded LegalPage chunk instead of the main bundle.
export type LegalDoc = "privacy" | "terms";

/** Map a URL path to a legal document, or null if it is not a legal page. */
export function legalDocForPath(pathname: string): LegalDoc | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/privacy") return "privacy";
  if (path === "/terms") return "terms";
  return null;
}
