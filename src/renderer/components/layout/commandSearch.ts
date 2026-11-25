/** Search matching for the Ctrl+K command palette. */

/** Lower-case and fold Arabic spelling variants (diacritics, tatweel, alef
 *  and teh-marbuta/yeh forms) so "الفوترة" / "فوتره" / "Billing" all match. */
export function normalizeSearch(text: string): string {
  return text
    .toLowerCase()
    .replace(/[\u064B-\u0652\u0670\u0640]/g, "")
    .replace(/[\u0622\u0623\u0625]/g, "\u0627")
    .replace(/\u0629/g, "\u0647")
    .replace(/\u0649/g, "\u064A")
    .trim();
}

export function matchesQuery(item: { label: string; sub?: string; keywords?: string[] }, query: string): boolean {
  const q = normalizeSearch(query);
  if (!q) return true;
  return [item.label, item.sub ?? "", ...(item.keywords ?? [])].some(f => normalizeSearch(f).includes(q));
}
