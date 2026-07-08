/**
 * Self-Healing Build System — unit + integration tests.
 * Run with: node tests/test_build_system.js
 */
import assert from "node:assert";
import path   from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

// CJS modules (tools/*.js) require a CJS require() bridge because the project
// uses "type":"module" but tools/*.js are CommonJS.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT      = path.resolve(__dirname, "..");
const cjsRequire = createRequire(import.meta.url);

const log        = cjsRequire(path.join(ROOT, "tools/logger.cjs"));
const bk         = cjsRequire(path.join(ROOT, "tools/backup-manager.cjs"));
const envChecker = cjsRequire(path.join(ROOT, "tools/env-checker.cjs"));
const hc         = cjsRequire(path.join(ROOT, "tools/health-check.cjs"));
const re         = cjsRequire(path.join(ROOT, "tools/repair-engine.cjs"));
const rm         = cjsRequire(path.join(ROOT, "tools/recovery-manager.cjs"));

// ── Mini test runner ───────────────────────────────────────────────────────────

let passed = 0, failed = 0;
const errors = [];

async function it(label, fn) {
  try {
    await fn();
    console.log(`  ✅ ${label}`);
    passed++;
  } catch (err) {
    console.log(`  ❌ ${label}`);
    console.log(`     ${err.message}`);
    errors.push({ label, message: err.message });
    failed++;
  }
}

function suite(name) { console.log(`\n📦 ${name}`); }

// ── logger ────────────────────────────────────────────────────────────────────

suite("logger");

await it("exports runtime, install, build, errors categories", () => {
  for (const cat of ["runtime", "install", "build", "errors"]) {
    assert.ok(log[cat], `missing: ${cat}`);
    for (const m of ["info", "warn", "error"]) {
      assert.strictEqual(typeof log[cat][m], "function");
    }
  }
});

await it("errorRecord accepts required fields without throwing", () => {
  assert.doesNotThrow(() =>
    log.errorRecord({ message: "test", rootCause: "unit test",
      repairAttempted: "none", repairResult: "skipped", nextAction: "ignore" })
  );
});

await it("LOG_DIR is a string path", () => {
  assert.strictEqual(typeof log.LOG_DIR, "string");
});

// ── backup-manager ────────────────────────────────────────────────────────────

suite("backup-manager");

await it("isAllowed permits package.json", () => {
  assert.ok(bk.isAllowed("package.json"));
});

await it("isAllowed rejects src/ paths", () => {
  assert.ok(!bk.isAllowed("src/renderer/App.tsx"));
});

await it("isAllowed rejects .py files", () => {
  assert.ok(!bk.isAllowed("app/factory.py"));
});

await it("isAllowed rejects tsx source files", () => {
  assert.ok(!bk.isAllowed("src/renderer/main.tsx"));
});

await it("create skips protected files and returns skipped list", () => {
  const res = bk.create(["src/renderer/App.tsx", "package.json"], "test");
  assert.ok(Array.isArray(res.skipped));
  assert.ok(res.skipped.some(s => s.path === "src/renderer/App.tsx"));
});

await it("list returns an array", () => {
  assert.ok(Array.isArray(bk.list()));
});

// ── env-checker ────────────────────────────────────────────────────────────────

suite("env-checker");

await it("nodeInfo returns version string and ok boolean", () => {
  const n = envChecker.nodeInfo();
  assert.ok(n.version.startsWith("v"));
  assert.ok(typeof n.ok === "boolean");
});

await it("detectPackageManager returns pm + source", () => {
  const pm = envChecker.detectPackageManager();
  assert.ok(["npm", "pnpm", "yarn", "bun"].includes(pm.pm));
  assert.ok(typeof pm.source === "string");
});

await it("checkPermissions returns all keys", () => {
  const perms = envChecker.checkPermissions();
  for (const key of ["home", "tmp", "cwd", "npmCache"]) {
    assert.ok(typeof perms[key].writable === "boolean");
  }
});

await it("checkEnvVars returns allRequiredPresent boolean", () => {
  const e = envChecker.checkEnvVars();
  assert.ok(typeof e.allRequiredPresent === "boolean");
  assert.ok(Array.isArray(e.missing));
});

await it("checkProjectFiles detects package.json", () => {
  const p = envChecker.checkProjectFiles();
  assert.ok(typeof p.packageJson.exists === "boolean");
  assert.ok(typeof p.packageJson.valid  === "boolean");
});

await it("snapshot returns full env report", async () => {
  const snap = await envChecker.snapshot();
  for (const key of ["node", "packageManager", "permissions", "project", "env", "ports"]) {
    assert.ok(snap[key] !== undefined, `missing: ${key}`);
  }
});

// ── health-check ──────────────────────────────────────────────────────────────

suite("health-check");

await it("run returns healthy boolean and score 0-100", async () => {
  const r = await hc.run();
  assert.ok(typeof r.healthy === "boolean");
  assert.ok(r.score >= 0 && r.score <= 100);
});

await it("run returns categories with valid statuses", async () => {
  const r = await hc.run();
  for (const cat of Object.values(r.categories)) {
    for (const c of cat) {
      assert.ok(["PASS", "WARN", "FAIL"].includes(c.status), `invalid status: ${c.status}`);
    }
  }
});

await it("SEV has three values", () => {
  assert.strictEqual(hc.SEV.PASS, "PASS");
  assert.strictEqual(hc.SEV.WARN, "WARN");
  assert.strictEqual(hc.SEV.FAIL, "FAIL");
});

// ── repair-engine ─────────────────────────────────────────────────────────────

suite("repair-engine");

await it("classify detects PERMISSION", () => {
  assert.strictEqual(re.classify("Error: EACCES permission denied", ""), re.FAILURE.PERMISSION);
});

await it("classify detects MISSING_MODULES", () => {
  assert.strictEqual(re.classify("Error: Cannot find module 'react'", ""), re.FAILURE.MISSING_MODULES);
});

await it("classify detects MISSING_PORT", () => {
  assert.strictEqual(re.classify("Error: EADDRINUSE address already in use", ""), re.FAILURE.MISSING_PORT);
});

await it("classify defaults to UNKNOWN", () => {
  assert.strictEqual(re.classify("something random", ""), re.FAILURE.UNKNOWN);
});

await it("patchConfig rejects src/ files", () => {
  const res = re.patchConfig("src/renderer/App.tsx", s => s, "test");
  assert.ok(!res.ok);
  assert.ok(res.error.includes("Not allowed"));
});

await it("RepairEngine.recover is a function", () => {
  assert.strictEqual(typeof re.RepairEngine.recover, "function");
});

await it("repairPermissions does not throw", () => {
  assert.doesNotThrow(() => re.repairPermissions());
});

// ── recovery-manager ──────────────────────────────────────────────────────────

suite("recovery-manager");

await it("exports all public functions", () => {
  for (const fn of ["runPipeline", "recoverFailure", "listBackups", "restoreBackup", "pruneBackups"]) {
    assert.strictEqual(typeof rm[fn], "function", `missing: ${fn}`);
  }
});

await it("runPipeline returns structured result", async () => {
  const res = await rm.runPipeline({ silent: true, maxAttempts: 1 });
  assert.ok(typeof res.ok === "boolean");
  assert.ok(Array.isArray(res.stages));
  assert.ok(typeof res.durationMs === "number");
});

await it("recoverFailure handles UNKNOWN gracefully", async () => {
  const res = await rm.recoverFailure({ stderr: "random error text", context: "test" });
  assert.ok(typeof res.ok === "boolean");
  assert.ok(typeof res.failureClass === "string");
});

// ── Summary ────────────────────────────────────────────────────────────────────

console.log(`\n${"─".repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed (${passed + failed} total)\n`);
if (errors.length) {
  console.log("Failed tests:");
  for (const e of errors) console.log(`  • ${e.label}: ${e.message}`);
  process.exit(1);
}
process.exit(0);
