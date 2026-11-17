/**
 * Assistant navigation (M2) — the AI can only *suggest* pages.
 *
 * The backend (app/core/ai/navigation.py) lets the model end a reply with
 * `[[open:<page-id>]]` markers. This module strips those markers from the
 * visible text and turns known page ids into suggestions the user clicks.
 * Nothing here changes data: the only effect is setPage().
 *
 * suggestPagesForPrompt() is a deterministic fallback for when the user
 * plainly asks to open a page ("افتح الإعدادات", "go to billing") and the
 * model forgot the marker.
 */
import type { Page } from "../types";

/** Every page the assistant may point to, with its sidebar.nav i18n key. */
export const ASSISTANT_PAGES: Record<string, { page: Page; navKey: string }> = {
  home:            { page: "home",          navKey: "home" },
  ai:              { page: "ai",            navKey: "ai" },
  "new-project":   { page: "new-project",   navKey: "newProject" },
  leads:           { page: "leads",         navKey: "leads" },
  automation:      { page: "automation",    navKey: "automation" },
  social:          { page: "social",        navKey: "social" },
  "app-builder":   { page: "app-builder",   navKey: "appBuilder" },
  design:          { page: "design",        navKey: "design" },
  dev:             { page: "dev",           navKey: "dev" },
  agentos:         { page: "agentos",       navKey: "agentos" },
  marketplace:     { page: "marketplace",   navKey: "marketplace" },
  plugins:         { page: "plugins",       navKey: "plugins" },
  integrations:    { page: "integrations",  navKey: "integrations" },
  runs:            { page: "runs",          navKey: "runs" },
  training:        { page: "training",      navKey: "trainingStudio" },
  "study-library": { page: "study-library", navKey: "studyLibrary" },
  careers:         { page: "careers",       navKey: "careers" },
  "business-lab":  { page: "business-lab",  navKey: "businessLab" },
  "saas-factory":  { page: "saas-factory",  navKey: "saasFactory" },
  discover:        { page: "discover",      navKey: "discover" },
  feed:            { page: "feed",          navKey: "feed" },
  devices:         { page: "devices",       navKey: "devices" },
  teams:           { page: "teams",         navKey: "teams" },
  organizations:   { page: "organizations", navKey: "organizations" },
  billing:         { page: "billing",       navKey: "billing" },
  settings:        { page: "settings",      navKey: "settings" },
  "ai-routing":    { page: "ai-routing",    navKey: "aiRouting" },
  observability:   { page: "observability", navKey: "observability" },
  sandbox:         { page: "sandbox",       navKey: "sandbox" },
};

const MAX_SUGGESTIONS = 2;
const MARKER = /\[\[\s*open\s*:\s*([a-z-]+)\s*\]\]/gi;
// A marker still arriving mid-stream ("…\n[[op") — hidden until complete.
const PARTIAL_TAIL = /\[(?:\[\s*(?:o|op|ope|open)?(?:\s*:\s*[a-z-]*)?)?$/i;

export interface NavExtraction {
  /** Reply text without markers. */
  text: string;
  /** Known pages, de-duplicated, in reply order, at most 2. */
  pages: Page[];
}

export function extractNavSuggestions(content: string): NavExtraction {
  const pages: Page[] = [];
  let text = content.replace(MARKER, (_m, id: string) => {
    const entry = ASSISTANT_PAGES[id.toLowerCase()];
    if (entry && !pages.includes(entry.page) && pages.length < MAX_SUGGESTIONS) pages.push(entry.page);
    return "";
  });
  text = text.replace(PARTIAL_TAIL, "").replace(/\n{3,}/g, "\n\n").trimEnd();
  return { text, pages };
}

const KEYWORDS: { page: Page; words: string[] }[] = [
  { page: "settings",      words: ["settings", "preferences", "إعدادات", "اعدادات", "الاعدادات"] },
  { page: "billing",       words: ["billing", "invoice", "subscription", "فوترة", "الفوترة", "فواتير", "اشتراك"] },
  { page: "leads",         words: ["leads", "عملاء محتمل", "العملاء المحتملين", "العملاء المحتملون"] },
  { page: "automation",    words: ["automation", "workflow", "أتمتة", "اتمتة", "الأتمتة"] },
  { page: "design",        words: ["design", "تصميم", "التصميم"] },
  { page: "app-builder",   words: ["app builder", "build an app", "بناء تطبيق", "أبني تطبيق"] },
  { page: "teams",         words: ["teams", "team", "الفرق", "فريق"] },
  { page: "organizations", words: ["organization", "مؤسسة", "المؤسسات"] },
  { page: "integrations",  words: ["integration", "تكامل", "التكاملات"] },
  { page: "marketplace",   words: ["marketplace", "templates", "القوالب", "قوالب"] },
  { page: "agentos",       words: ["agents", "الوكلاء", "وكلاء"] },
  { page: "training",      words: ["training", "courses", "التدريب", "الدورات", "الكورسات"] },
  { page: "devices",       words: ["devices", "الأجهزة", "اجهزة"] },
  { page: "social",        words: ["marketing", "social", "التسويق"] },
  { page: "careers",       words: ["careers", "jobs", "الوظائف", "وظيفة"] },
  { page: "new-project",   words: ["new project", "مشروع جديد"] },
  { page: "home",          words: ["dashboard", "home", "الرئيسية", "لوحة التحكم"] },
];

const OPEN_VERBS = /\b(open|go to|show me|take me to|navigate to)\b|(افتح|افتحي|اذهب|إذهب|روح|انتقل|خذني|ودني|وديني|اعرض)/i;

/** Pages the user explicitly asked to open, matched on keywords + an "open" verb. */
export function suggestPagesForPrompt(input: string): Page[] {
  const text = input.toLowerCase().trim();
  if (!text || !OPEN_VERBS.test(text)) return [];
  const pages: Page[] = [];
  for (const { page, words } of KEYWORDS) {
    if (words.some(w => text.includes(w)) && !pages.includes(page)) pages.push(page);
    if (pages.length >= MAX_SUGGESTIONS) break;
  }
  return pages;
}

export function navLabelKey(page: Page): string {
  const entry = Object.values(ASSISTANT_PAGES).find(e => e.page === page);
  return `common:sidebar.nav.${entry?.navKey ?? page}`;
}
