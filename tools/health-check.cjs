/**
 * Health Check — validates the build environment before every execution.
 *
 * Checks: filesystem, permissions, dependencies, runtime, ports, env vars.
 * Returns a structured report and a single boolean `healthy`.
 * Never modifies anything; pure read-only diagnostics.
 */
"use strict";

const fs   = require("fs");
const path = require("path");
const os   = require("os");

const env  = require("./env-checker.cjs");
const log  = require("./logger.cjs");

// ── Severity levels ────────────────────────────────────────────────────────────

const SEV = { PASS: "PASS", WARN: "WARN", FAIL: "FAIL" };

function check(label, passed, warnOnly, detail) {
  return { label, status: passed ? SEV.PASS : warnOnly ? SEV.WARN : SEV.FAIL, detail };
}

// ── Individual checks ──────────────────────────────────────────────────────────

async function checkFilesystem() {
  const root = path.resolve(__dirname, "..");
  const items = ["package.json", "vite.config.ts", "tsconfig.json"];
  const missing = items.filter(f => !fs.existsSync(path.join(root, f)));

  return [
    check("project root exists",   fs.existsSync(root),          false, root),
    check("required config files", missing.length === 0,          false, missing.length ? `missing: ${missing.join(", ")}` : "all present"),
    check("node_modules installed",
      fs.existsSync(path.join(root, "node_modules")),             true,  "run npm install"),
  ];
}

async function checkPermissions() {
  const perms = env.checkPermissions();
  return [
    check("cwd writable",   perms.cwd.writable,          false, perms.cwd.path),
    check("HOME writable",  perms.home.writable,          true,  perms.home.path),
    check("tmp writable",   perms.tmp.writable,           false, perms.tmp.path),
    check("npm cache accessible",
      perms.npmCache.writable || perms.fallbackCache.writable,
      true, perms.npmCache.path),
  ];
}

async function checkRuntime() {
  const node = env.nodeInfo();
  const pm   = env.detectPackageManager();
  const pmVer = env.pmVersion(pm.pm);

  return [
    check(`Node.js >= 18`, node.ok,    false, `found ${node.version}`),
    check("package manager", !!pmVer,  false, pmVer ? `${pm.pm} ${pmVer} (${pm.source})` : "none found"),
  ];
}

async function checkDependencies() {
  const proj = env.checkProjectFiles();
  return [
    check("package.json valid", proj.packageJson.valid,         false, ""),
    check("lockfile present",   proj.lockfile.exists,           true,  "run npm install to generate"),
    check("node_modules exist", proj.nodeModules.exists,        true,  "run npm install"),
    check("vite config",        proj.viteConfig.exists,         false, ""),
    check("tsconfig.json",      proj.tsConfig.exists,           false, ""),
  ];
}

async function checkPorts() {
  const results = await env.checkPorts();
  return results.map(({ port, available }) =>
    check(`port ${port} available`, available, true, available ? "free" : "in use")
  );
}

async function checkEnv() {
  const e = env.checkEnvVars();
  return [
    check("required env vars", e.allRequiredPresent, false,
      e.missing.length ? `missing: ${e.missing.join(", ")}` : "all present"),
    check("ANTHROPIC_API_KEY",
      !!process.env.ANTHROPIC_API_KEY, true, "optional — needed for AgentOS AI features"),
  ];
}

// ── Full health report ─────────────────────────────────────────────────────────

/**
 * Run all checks and return a structured report.
 * @returns {Promise<{
 *   healthy: boolean,
 *   score: number,        // 0-100
 *   checks: object[],
 *   categories: object,
 *   ts: string,
 * }>}
 */
async function run() {
  const categories = {
    filesystem  : await checkFilesystem(),
    permissions : await checkPermissions(),
    runtime     : await checkRuntime(),
    dependencies: await checkDependencies(),
    ports       : await checkPorts(),
    environment : await checkEnv(),
  };

  const all   = Object.values(categories).flat();
  const fails = all.filter(c => c.status === SEV.FAIL).length;
  const warns = all.filter(c => c.status === SEV.WARN).length;
  const pass  = all.filter(c => c.status === SEV.PASS).length;

  const score   = Math.round((pass / all.length) * 100);
  const healthy = fails === 0;

  const report = { healthy, score, fails, warns, pass, total: all.length, categories, ts: new Date().toISOString() };

  if (!healthy) {
    log.errorRecord({
      message       : "Health check FAILED",
      rootCause     : `${fails} critical check(s) failed`,
      repairAttempted: null,
      repairResult  : null,
      nextAction    : "Run npm run doctor for detailed diagnostics",
    });
  } else if (warns > 0) {
    log.runtime.warn("Health check PASS with warnings", { warns, score });
  } else {
    log.runtime.info("Health check PASS", { score });
  }

  return report;
}

module.exports = { run, SEV };
