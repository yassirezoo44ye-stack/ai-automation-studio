// Runtime UI audit (FE-03 / FE-04): drives the real built app in Chromium.
//
// Unlike scripts/audit-ui-actions.mjs (a source inventory), this opens every
// signed-in route and records what a user actually gets:
//   layout   every route x viewport x language: page-level horizontal
//            scroll, content that escapes the screen or is cut off by a
//            clipping container, overlapping controls, <html dir>, raw
//            translation keys on screen, unnamed controls, small touch targets
//   actions  every route (desktop, English): every visible button and link,
//            and what clicking it does (navigation, request, DOM change,
//            dialog, nothing). Names matching DESTRUCTIVE are listed but not
//            clicked.
//
// Needs the built SPA served with the API on the same origin and a signed-in
// SYNTHETIC account (never a real customer):
//   FLOW_UI_URL=http://localhost:5180 FLOW_UI_EMAIL=... FLOW_UI_PASSWORD=... \
//     node scripts/ui-runtime-audit.mjs layout|actions out.json
import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.FLOW_UI_URL ?? "http://localhost:5180";
const EMAIL = process.env.FLOW_UI_EMAIL;
const PASSWORD = process.env.FLOW_UI_PASSWORD;
const [mode = "layout", out] = process.argv.slice(2);

export const ROUTES = process.env.FLOW_UI_ROUTES ? process.env.FLOW_UI_ROUTES.split(",") : ["/home", "/ai", "/dev", "/design", "/automation", "/agentos", "/marketplace",
  "/plugins", "/sandbox", "/ai-routing", "/observability", "/organizations", "/teams", "/billing",
  "/social", "/settings", "/app-builder", "/runs", "/integrations", "/training", "/devices",
  "/business-lab", "/discover", "/feed", "/careers", "/study-library", "/leads", "/saas-factory",
  "/new-project"];

const ALL_VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900, touch: false },
  { name: "tablet-portrait", width: 768, height: 1024, touch: true },
  { name: "tablet-landscape", width: 1024, height: 768, touch: true },
  { name: "android-portrait", width: 412, height: 915, touch: true },
  { name: "android-landscape", width: 915, height: 412, touch: true },
  { name: "small-phone", width: 360, height: 740, touch: true },
];

export const VIEWPORTS = process.env.FLOW_UI_VIEWPORTS
  ? ALL_VIEWPORTS.filter(v => process.env.FLOW_UI_VIEWPORTS.split(",").includes(v.name)) : ALL_VIEWPORTS;
const LANGS = (process.env.FLOW_UI_LANGS ?? "en,ar").split(",");

// Saved preferences (some server-side): clicked a second time to restore.
const TOGGLES = /collapse|expand|light mode|dark mode|sidebar|العربية|english|الوضع/i;
const DESTRUCTIVE = /delete|remove|revoke|log ?out|sign ?out|disconnect|cancel (plan|subscription)|wipe|reset|archive|حذف|إزالة|خروج|إلغاء الاشتراك/i;

if (!EMAIL || !PASSWORD) {
  console.error("Set FLOW_UI_EMAIL and FLOW_UI_PASSWORD (synthetic account).");
  process.exit(2);
}

// /api/auth/refresh shares the 10-per-minute-per-IP "auth" limit with login,
// and every full page load refreshes the session. The audit loads pages far
// faster than a person, so each load gets its own synthetic client address
// (honoured only behind a proxy the backend trusts, as in local runs).
let ipSeq = 0;
const nextIp = () => `10.96.${Math.floor(++ipSeq / 250) % 250}.${(ipSeq % 250) + 1}`;
async function load(page, url) {
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": nextIp() });
  await page.goto(url);
}

async function signIn(browser, touch) {
  const r = await fetch(`${BASE}/api/auth/login`, {
    method: "POST", headers: { "content-type": "application/json", "X-Forwarded-For": nextIp() },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!r.ok) throw new Error(`login failed: ${r.status}`);
  const { refresh_token } = await r.json();
  const ctx = await browser.newContext({ hasTouch: touch, isMobile: touch });
  await ctx.addInitScript(t => {
    if (!localStorage.getItem("axon_refresh_token")) localStorage.setItem("axon_refresh_token", t);
  }, refresh_token);
  return ctx;
}

const goto = (page, route) => page.evaluate(r => {
  history.pushState({}, "", r); dispatchEvent(new PopStateEvent("popstate"));
}, route);

/** Runs in the page: layout findings for the current screen. */
function inspect(touch) {
  const vw = window.innerWidth;
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0;
  };
  const label = el => {
    const id = el.id ? `#${el.id}` : "";
    const cls = typeof el.className === "string" && el.className.trim()
      ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
    const text = (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 40);
    return `${el.tagName.toLowerCase()}${id}${cls}${text ? ` "${text}"` : ""}`;
  };
  // Nearest ancestor that clips horizontally, and whether it can scroll.
  const clipBox = el => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox !== "visible") return { box: p.getBoundingClientRect(), scrolls: ox === "auto" || ox === "scroll", el: p };
    }
    return { box: { left: 0, right: vw }, scrolls: false, el: null };
  };
  // Leaf content a user must be able to see: text, controls, images.
  const content = [...document.querySelectorAll("body *")].filter(el =>
    visible(el) && !el.closest("svg")
    && (el.matches("button, a, input, select, textarea, img, [role=button], [role=tab]")
      || [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())));
  const escaping = [], cut = [], scrollAreas = new Set();
  for (const el of content) {
    const r = el.getBoundingClientRect();
    const c = clipBox(el);
    const left = Math.max(c.box.left, 0), right = Math.min(c.box.right, vw);
    if (r.right <= right + 1 && r.left >= left - 1) continue;
    // Entirely outside: a closed off-canvas drawer, hidden by design.
    if (r.left >= right - 1 || r.right <= left + 1) continue;
    // Inside an on-screen scroll container: reachable by scrolling it.
    if (c.scrolls && c.box.right <= vw + 1 && c.box.left >= -1) { scrollAreas.add(label(c.el)); continue; }
    const entry = `${label(el)} [${Math.round(r.left)}..${Math.round(r.right)} of ${Math.round(left)}..${Math.round(right)}]`;
    (c.el ? cut : escaping).push(entry);
  }
  // Controls drawn over other controls (e.g. a fixed button over a header).
  const ctrls = [...document.querySelectorAll("button, a[href], input, [role=button]")].filter(visible);
  const overlaps = [];
  for (let i = 0; i < ctrls.length && overlaps.length < 6; i++) for (let j = i + 1; j < ctrls.length; j++) {
    const A = ctrls[i], B = ctrls[j];
    if (A.contains(B) || B.contains(A)) continue;
    const a = A.getBoundingClientRect(), b = B.getBoundingClientRect();
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    if (w <= 6 || h <= 6) continue;
    // Ignore a pair when the shared spot is scrolled out of either one's
    // clipping container (e.g. a scrollable list running under a footer).
    const x = Math.max(a.left, b.left) + w / 2, y = Math.max(a.top, b.top) + h / 2;
    const inClip = el => { for (let p = el.parentElement; p; p = p.parentElement) {
      if (getComputedStyle(p).overflow === "visible") continue;
      const c = p.getBoundingClientRect(); if (x < c.left || x > c.right || y < c.top || y > c.bottom) return false;
    } return true; };
    if (inClip(A) && inClip(B)) overlaps.push(`${label(A)} x ${label(B)}`);
  }
  const controls = [...document.querySelectorAll("button, a[href], [role=button], input, select, textarea")].filter(visible);
  const unnamed = controls.filter(el => {
    if (el.matches("input[type=hidden]")) return false;
    const name = (el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || el.getAttribute("title")
      || (el.labels && el.labels.length ? "label" : "") || el.innerText || el.getAttribute("placeholder") || el.value || "").trim();
    return !name;
  }).map(label);
  const small = touch ? controls.filter(el => el.matches("button, a[href], [role=button]")).filter(el => {
    const r = el.getBoundingClientRect(); return r.width < 24 || r.height < 24;
  }).map(el => `${label(el)} ${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`) : [];
  const text = document.body.innerText;
  const rawKeys = [...new Set(text.match(/\b[a-z][a-zA-Z]+\.[a-z][a-zA-Z]+(\.[a-zA-Z]+)+\b/g) ?? [])]
    .filter(k => !/\.(com|ai|app|io|js|ts|md|json|net|org)$/.test(k)).slice(0, 10);
  return {
    dir: document.documentElement.dir || "ltr",
    pageScrollX: Math.max(0, document.documentElement.scrollWidth - vw),
    escaping: escaping.slice(0, 8), escapingCount: escaping.length, cut: cut.slice(0, 8), cutCount: cut.length,
    scrollAreas: [...scrollAreas].slice(0, 5), overlaps,
    unnamedControls: unnamed.slice(0, 10), unnamedCount: unnamed.length,
    smallTouchTargets: small.slice(0, 10), smallTouchCount: small.length,
    rawKeys,
    crashed: /Error in [\w-]+|Something went wrong|new version of Flow|Connection error/.test(text),
  };
}

async function layout(browser) {
  const rows = [];
  for (const touch of [false, true].filter(t => VIEWPORTS.some(v => v.touch === t))) {
    const ctx = await signIn(browser, touch);
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(e.message.slice(0, 160)));
    for (const lang of LANGS) {
      await page.addInitScript(l => localStorage.setItem("axon-lang", l), lang);
      for (const vp of VIEWPORTS.filter(v => v.touch === touch)) {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await load(page, `${BASE}/home`);
        await page.waitForTimeout(2500);
        for (const route of ROUTES) {
          errors.length = 0;
          await goto(page, route);
          await page.waitForTimeout(1200);
          const f = await page.evaluate(inspect, touch);
          rows.push({ route, viewport: vp.name, lang, ...f, pageErrors: [...errors] });
        }
        process.stderr.write(`layout ${lang} ${vp.name} done\n`);
      }
    }
    await ctx.close();
  }
  return rows;
}

/** Runs in the page: visible clickable controls in document order. */
function listControls() {
  const controlName = el => (el.getAttribute("aria-label") || el.innerText || el.getAttribute("title") || "").trim().replace(/\s+/g, " ").slice(0, 60);
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  return [...document.querySelectorAll("button, a[href], [role=button], [role=tab], [role=menuitem]")]
    .filter(visible)
    .map((el, i, all) => ({
      i,
      nth: all.slice(0, i).filter(o => controlName(o) === controlName(el)).length,
      kind: el.tagName === "A" ? "link" : (el.getAttribute("role") || "button"),
      name: (el.getAttribute("aria-label") || el.innerText || el.getAttribute("title") || "").trim().replace(/\s+/g, " ").slice(0, 60),
      href: el.getAttribute("href"),
      target: el.getAttribute("target"),
      rel: el.getAttribute("rel"),
      disabled: el.disabled === true || el.getAttribute("aria-disabled") === "true",
      inSidebar: !!el.closest("aside, nav"),
    }));
}

async function actions(browser) {
  const ctx = await signIn(browser, false);
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => localStorage.setItem("axon-lang", "en"));
  await load(page, `${BASE}/home`);
  await page.waitForTimeout(2500);
  const results = [];
  let sidebarDone = false;
  for (const route of ROUTES) {
    await goto(page, route);
    await page.waitForTimeout(1500);
    const controls = await page.evaluate(listControls);
    for (const c of controls) {
      if (c.inSidebar && sidebarDone) continue;      // shared chrome: test once
      const row = { route, ...c };
      if (c.disabled) { results.push({ ...row, outcome: "disabled" }); continue; }
      if (c.href !== null && c.kind === "link") {
        const h = c.href.trim();
        row.linkIssue = !h || h === "#" || h.startsWith("javascript:") ? "dead href"
          : c.target === "_blank" && !/noopener|noreferrer/.test(c.rel ?? "") ? "_blank without noopener" : null;
        if (/^https?:/.test(h) && !h.startsWith(BASE)) {   // external: check, don't follow
          try {
            const r = await fetch(h, { method: "HEAD", redirect: "follow", signal: AbortSignal.timeout(8000) });
            row.outcome = `external ${r.status}`;
          } catch (e) { row.outcome = `external unreachable (${e.cause?.code ?? e.name})`; }
          results.push(row); continue;
        }
      }
      if (DESTRUCTIVE.test(c.name)) { results.push({ ...row, outcome: "not clicked (destructive)" }); continue; }
      // Fresh page for each click, so one click cannot change the next.
      await load(page, `${BASE}${route}`);
      await page.waitForTimeout(2200);
      const before = { url: page.url(), html: await page.evaluate(() => document.body.innerHTML.length) };
      let requests = 0, dialog = false;
      const errors = [];
      const onReq = r => { if (r.url().includes("/api/")) requests++; };
      const onErr = e => errors.push(e.message.slice(0, 160));
      const onDialog = d => { dialog = true; void d.dismiss(); };
      page.on("request", onReq); page.on("pageerror", onErr); page.on("dialog", onDialog);
      const popup = ctx.waitForEvent("page", { timeout: 1500 }).catch(() => null);
      try {
        // Find the control again by its name (and which one of that name).
        const target = (await page.evaluateHandle(({ name, nth }) => {
          const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
          const nm = el => (el.getAttribute("aria-label") || el.innerText || el.getAttribute("title") || "").trim().replace(/\s+/g, " ").slice(0, 60);
          return [...document.querySelectorAll("button, a[href], [role=button], [role=tab], [role=menuitem]")]
            .filter(el => visible(el) && nm(el) === name)[nth] ?? null;
        }, { name: c.name, nth: c.nth })).asElement();
        if (!target) { row.outcome = "not found after reload"; }
        else if (c.kind === "link" && /^#./.test(c.href ?? "")) {
          // In-page anchor (e.g. "Skip to main content"): its target must exist.
          row.outcome = await page.evaluate(h => document.getElementById(h.slice(1)) ? "anchor ok" : "anchor target missing", c.href);
        }
        else {
          await target.click({ timeout: 3000, noWaitAfter: true });
          await page.waitForTimeout(1200);
          const newPage = await popup;
          if (newPage) { row.opened = newPage.url(); await newPage.close(); }
          const after = { url: page.url(), html: await page.evaluate(() => document.body.innerHTML.length) };
          const crashed = await page.evaluate(() => /Error in [\w-]+|Something went wrong/.test(document.body.innerText));
          row.outcome = crashed ? "error screen"
            : errors.length ? "uncaught error"
            : row.opened ? "opened tab"
            : after.url !== before.url ? `navigated ${new URL(after.url).pathname}`
            : dialog ? "native dialog"
            : requests ? `request x${requests}`
            : after.html !== before.html ? "ui changed"
            : "no visible effect";
          if (errors.length) row.errors = errors;
          // Put view toggles back so the next control sees the same screen.
          if (TOGGLES.test(c.name)) {
            await target.click({ timeout: 2000 }).catch(() => {});
            await page.waitForTimeout(800);
          }
        }
      } catch (e) {
        row.outcome = `click failed: ${e.message.split("\n")[0].slice(0, 100)}`;
      } finally {
        page.off("request", onReq); page.off("pageerror", onErr); page.off("dialog", onDialog);
        await page.keyboard.press("Escape").catch(() => {});
      }
      results.push(row);
      if (page.url() !== `${BASE}${route}`) { await load(page, `${BASE}${route}`); await page.waitForTimeout(1500); }
    }
    sidebarDone = true;
    process.stderr.write(`actions ${route}: ${controls.length} controls\n`);
    if (controls.length < 3) {
      process.stderr.write(`  at ${page.url()}: ${(await page.evaluate(() => document.body.innerText)).slice(0, 200).replace(/\s+/g, " ")}\n`);
    }
    if (out) fs.writeFileSync(out, JSON.stringify(results, null, 1) + "\n");   // partial progress
  }
  await ctx.close();
  return results;
}

const browser = await chromium.launch();
try {
  const data = mode === "actions" ? await actions(browser) : await layout(browser);
  const json = JSON.stringify(data, null, 1) + "\n";
  if (out) fs.writeFileSync(out, json); else process.stdout.write(json);
} finally {
  await browser.close();
}
