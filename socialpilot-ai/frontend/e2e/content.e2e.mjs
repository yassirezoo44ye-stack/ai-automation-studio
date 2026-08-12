// Phase 2 end-to-end smoke test: drives the real browser against the real
// frontend dev server and the real backend + Postgres — the only thing
// mocked is the AI provider itself, via AI_PROVIDER=mock on the backend
// (see backend/app/services/ai/mock_provider.py). No real/paid AI API key
// is required to run this test. Exercises the acceptance flow from the
// product spec: register -> Content Strategy -> add pillar -> Generate ->
// generate ideas (deterministic mock) -> save -> Library -> reload ->
// verify persistence.
//
// Prerequisites (not started by this script):
//   - Postgres reachable at the backend's DATABASE_URL, migrated to head
//   - backend running with AI_PROVIDER=mock, e.g.:
//       AI_PROVIDER=mock uvicorn app.main:app --port 8000
//   - frontend dev server running on FRONTEND_APP_URL
//
// Usage:
//   AI_PROVIDER=mock uvicorn app.main:app --port 8000   # backend, in one terminal
//   npm run dev                                          # frontend, in another
//   npm run test:e2e:content                             # this script, in a third
//
// Env overrides: APP_URL (default http://localhost:5173),
// PLAYWRIGHT_CHROMIUM_PATH (default: let Playwright auto-detect).
import { chromium } from "playwright";

const APP_URL = process.env.APP_URL ?? "http://localhost:5173";
const launchOptions = process.env.PLAYWRIGHT_CHROMIUM_PATH
  ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
  : {};

const email = `e2e-content-${Date.now()}@example.com`;
const strategyName = `E2E Strategy ${Date.now()}`;
const pillarName = "AI Tools";

const browser = await chromium.launch(launchOptions);
const page = await browser.newPage();
const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => consoleErrors.push(String(err)));

try {
  // 1. Register a fresh account (own org, own tenant — isolates this run
  // from any other data in the dev DB).
  await page.goto(APP_URL + "/register");
  await page.fill("#full_name", "E2E Content Tester");
  await page.fill("#email", email);
  await page.fill("#password", "Sup3rSecret1");
  await page.fill("#org_name", "E2E Content Org");
  await page.click("button[type=submit]");
  await page.waitForURL("**/dashboard");
  console.log("OK: registered and landed on dashboard");

  // 2. Open Content Strategy and create a strategy.
  await page.click("text=Strategy");
  await page.waitForURL("**/content/strategy");
  await page.click("text=+ New Strategy");
  await page.fill("#strategy-name", strategyName);
  await page.fill("#business-description", "We sell AI-powered productivity tools.");
  await page.fill("#target-audience", "Busy knowledge workers");
  await page.fill("#goals", "Grow brand awareness");
  await page.fill("#brand-voice", "Friendly, practical, a little witty");
  await page.click("text=Create Strategy");
  await page.waitForSelector(`text=${strategyName}`);
  console.log("OK: created content strategy");

  // 3. Add a content pillar.
  await page.fill("input[placeholder^='Pillar name']", pillarName);
  await page.click("text=Add Pillar");
  await page.waitForSelector(`text=${pillarName}`);
  console.log("OK: added content pillar");

  // 4. Open the generator.
  await page.click("text=Generate");
  await page.waitForURL("**/content/generate");
  await page.waitForSelector("#strategy-select");

  // 5. Generate ideas using the deterministic mock AI provider (the
  // backend must be started with AI_PROVIDER=mock — see header comment).
  await page.click("text=Generate Ideas");
  await page.waitForSelector("text=5 AI tools your team isn't using yet", { timeout: 15000 });
  console.log("OK: generated ideas via mock AI provider");

  // 6. Save the first idea to the library.
  const savedButtons = page.locator("button:has-text('Save to Library')");
  await savedButtons.first().click();
  await page.waitForSelector("text=Saved ✓");
  console.log("OK: saved generated idea to library");

  // 7. Open the library and verify the saved item is there.
  await page.click("text=Library");
  await page.waitForURL("**/content/library");
  await page.waitForSelector("text=5 AI tools your team isn't using yet", { timeout: 10000 });
  console.log("OK: saved content visible in library");

  // 8. Reload and verify persistence (real DB row, not client-side state).
  await page.reload();
  await page.waitForSelector("text=5 AI tools your team isn't using yet", { timeout: 10000 });
  console.log("OK: saved content persists after reload");

  if (consoleErrors.length) {
    console.log(`NOTE: ${consoleErrors.length} browser console error(s) logged`);
  }
  console.log("ALL CONTENT E2E CHECKS PASSED");
} catch (err) {
  console.error("CONTENT E2E TEST FAILED:", err);
  console.error("console errors so far:", consoleErrors);
  process.exitCode = 1;
} finally {
  await browser.close();
}
