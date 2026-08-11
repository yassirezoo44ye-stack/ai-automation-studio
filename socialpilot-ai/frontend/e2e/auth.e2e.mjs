// Phase 1 end-to-end smoke test: drives the real browser against the real
// frontend dev server and the real backend + Postgres — no mocks. Exercises
// the full register -> dashboard -> reload (silent refresh) -> logout ->
// protected-route-redirect -> login loop described in the product spec's
// acceptance criteria for authentication.
//
// Prerequisites (not started by this script):
//   - backend running on FRONTEND_APP_URL's paired API (see API_BASE_URL)
//   - frontend dev server running on FRONTEND_APP_URL
//
// Usage:
//   npm run dev                        # in one terminal (frontend)
//   uvicorn app.main:app --port 8000   # in another (backend), see backend/README
//   npm run test:e2e                   # in a third
//
// Env overrides: APP_URL (default http://localhost:5173),
// PLAYWRIGHT_CHROMIUM_PATH (default: let Playwright auto-detect).
import { chromium } from "playwright";

const APP_URL = process.env.APP_URL ?? "http://localhost:5173";
const launchOptions = process.env.PLAYWRIGHT_CHROMIUM_PATH
  ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
  : {};

const email = `e2e-${Date.now()}@example.com`;

const browser = await chromium.launch(launchOptions);
const page = await browser.newPage();
const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => consoleErrors.push(String(err)));

try {
  // 1. Landing page — the exact UX flow described in the product spec ("What
  // do you want to publish?" composer -> Create Automation).
  await page.goto(APP_URL + "/");
  await page.waitForSelector("text=What do you want to publish?");
  await page.fill("textarea", "أريد محتوى عن الذكاء الاصطناعي، انشر منشورًا كل ساعة.");
  await page.click("text=Create Automation");

  // Not authenticated -> should land on /register carrying the draft prompt
  await page.waitForURL("**/register");
  console.log("OK: landing -> register redirect");

  // 2. Register: real API call, real Postgres row, real password hashing.
  await page.fill("#full_name", "E2E Tester");
  await page.fill("#email", email);
  await page.fill("#password", "Sup3rSecret1");
  await page.fill("#org_name", "E2E Org");
  await page.click("button[type=submit]");

  await page.waitForURL("**/dashboard");
  await page.waitForSelector("text=Welcome back, E2E Tester");
  await page.waitForSelector("text=E2E Org");
  const draftVisible = await page.isVisible("text=Natural-language automation planning");
  console.log("OK: register -> dashboard, draft prompt notice visible =", draftVisible);

  // 3. Reload: the access token is memory-only by design (see
  // src/api/tokenStore.ts) — this proves the httpOnly refresh cookie +
  // silent-refresh-on-bootstrap flow actually restores the session.
  await page.reload();
  await page.waitForSelector("text=Welcome back, E2E Tester", { timeout: 5000 });
  console.log("OK: session restored after reload via refresh cookie");

  // 4. Logout: refresh token must be revoked server-side, not just forgotten
  // client-side (see backend/tests/integration/test_auth_api.py for the
  // server-side assertion of this; here we just check the client UX).
  await page.click("text=Log out");
  await page.waitForURL(APP_URL + "/");
  await page.waitForSelector("text=Get started");
  console.log("OK: logout returns to landing, logged-out nav shown");

  // 5. Protected route redirects when logged out.
  await page.goto(APP_URL + "/dashboard");
  await page.waitForURL("**/login");
  console.log("OK: protected route redirects to /login when unauthenticated");

  // 6. Log back in with the same credentials.
  await page.fill("#email", email);
  await page.fill("#password", "Sup3rSecret1");
  await page.click("button[type=submit]");
  await page.waitForURL("**/dashboard");
  await page.waitForSelector("text=Welcome back, E2E Tester");
  console.log("OK: login works");

  if (consoleErrors.length) {
    console.log(`NOTE: ${consoleErrors.length} browser console error(s) logged (expected: the pre-login silent-refresh attempt 401s before any session exists)`);
  }
  console.log("ALL E2E CHECKS PASSED");
} catch (err) {
  console.error("E2E TEST FAILED:", err);
  console.error("console errors so far:", consoleErrors);
  process.exitCode = 1;
} finally {
  await browser.close();
}
