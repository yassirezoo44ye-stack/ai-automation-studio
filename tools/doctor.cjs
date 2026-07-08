#!/usr/bin/env node
/**
 * npm run doctor — project health diagnostics.
 *
 * Prints: Node version, package manager, permissions, cache, dependencies,
 * entry point, port availability, environment variables, build readiness.
 *
 * Exit codes: 0 = healthy, 1 = warnings, 2 = critical failures.
 */
"use strict";

// Windows UTF-8 safety
if (process.stdout.isTTY && process.platform === "win32") {
  try { process.stdout.setEncoding("utf8"); } catch (_) { /* ok */ }
}

const path   = require("path");
const fs     = require("fs");

const health    = require("./health-check.cjs");
const env       = require("./env-checker.cjs");
const bk        = require("./backup-manager.cjs");
const bus       = require("./event-bus.cjs");
const telemetry = require("./telemetry.cjs");

const ROOT = path.resolve(__dirname, "..");

// ── Colours (no external dep) ──────────────────────────────────────────────────

const C = {
  reset : "\x1b[0m",
  bold  : "\x1b[1m",
  green : "\x1b[32m",
  yellow: "\x1b[33m",
  red   : "\x1b[31m",
  cyan  : "\x1b[36m",
  grey  : "\x1b[90m",
};

const useColor = process.stdout.isTTY !== false;
const clr = (code, text) => useColor ? `${code}${text}${C.reset}` : text;

function icon(status) {
  if (status === "PASS") return clr(C.green,  "✅");
  if (status === "WARN") return clr(C.yellow, "⚠️ ");
  return clr(C.red, "❌");
}

function header(title) {
  console.log(`\n${clr(C.bold + C.cyan, `── ${title} `)}`);
}

function row(label, value, status) {
  const pad = 28;
  const lbl = label.padEnd(pad);
  const ico = status ? icon(status) + " " : "   ";
  console.log(`  ${ico}${lbl} ${clr(C.grey, String(value))}`);
}

// ── Section printers ───────────────────────────────────────────────────────────

function printOverview(snapshot, healthReport) {
  const healthy = healthReport.healthy;
  const score   = healthReport.score;
  const scoreColor = score >= 90 ? C.green : score >= 70 ? C.yellow : C.red;

  console.log(`\n${clr(C.bold, "🩺 AI Automation Studio — Build Doctor")}`);
  console.log(`  Health Score: ${clr(scoreColor + C.bold, `${score}/100`)}  |  Status: ${healthy ? clr(C.green, "HEALTHY") : clr(C.red, "ISSUES DETECTED")}`);
  console.log(`  ${clr(C.grey, new Date().toISOString())}`);
}

function printCategories(healthReport) {
  for (const [cat, checks] of Object.entries(healthReport.categories)) {
    header(cat.replace("-", " ").toUpperCase());
    for (const c of checks) {
      row(c.label, c.detail || "", c.status);
    }
  }
}

async function printSnapshot(snapshot) {
  header("RUNTIME SNAPSHOT");
  row("Node.js",        snapshot.node.version,                                snapshot.node.ok ? "PASS" : "FAIL");
  row("Package Manager",`${snapshot.packageManager.pm} ${snapshot.packageManager.version || "not found"} [${snapshot.packageManager.source}]`,
    snapshot.packageManager.version ? "PASS" : "FAIL");
  row("HOME",           snapshot.permissions.home.path,                        snapshot.permissions.home.writable ? "PASS" : "WARN");
  row("CWD writable",   snapshot.permissions.cwd.path,                         snapshot.permissions.cwd.writable  ? "PASS" : "FAIL");
  row("tmp writable",   snapshot.permissions.tmp.path,                         snapshot.permissions.tmp.writable  ? "PASS" : "WARN");
  row("npm cache",      snapshot.permissions.npmCache.path,                    snapshot.permissions.npmCache.writable ? "PASS" : "WARN");

  header("DEPENDENCY INTEGRITY");
  const proj = snapshot.project;
  row("package.json",  proj.packageJson.exists ? (proj.packageJson.valid ? "valid JSON" : "invalid JSON") : "NOT FOUND",
    proj.packageJson.valid ? "PASS" : "FAIL");
  row("lockfile",      proj.lockfile.exists ? "present" : "missing",          proj.lockfile.exists ? "PASS" : "WARN");
  row("node_modules",  proj.nodeModules.exists ? "present" : "missing",       proj.nodeModules.exists ? "PASS" : "WARN");
  row("vite.config",   proj.viteConfig.exists ? "found" : "missing",          proj.viteConfig.exists ? "PASS" : "FAIL");
  row("tsconfig.json", proj.tsConfig.exists   ? "found" : "missing",          proj.tsConfig.exists   ? "PASS" : "FAIL");

  header("SCRIPTS");
  for (const [k, v] of Object.entries(proj.scripts)) {
    row(`npm run ${k}`, v ? "defined" : "missing", v ? "PASS" : "WARN");
  }

  if (proj.entrypoint) {
    row("entry point", proj.entrypoint.path, proj.entrypoint.exists ? "PASS" : "FAIL");
  }

  header("ENVIRONMENT VARIABLES");
  const envV = snapshot.env;
  if (envV.missing.length) {
    for (const v of envV.missing) row(v, "MISSING — required",  "FAIL");
  }
  for (const v of envV.present) row(v, "present",              "PASS");
  for (const v of envV.absent)  row(v, "not set (optional)",   "WARN");

  header("PORT AVAILABILITY");
  for (const { port, available } of snapshot.ports) {
    row(`port ${port}`, available ? "free" : "in use", available ? "PASS" : "WARN");
  }
}

function printBackups() {
  header("BACKUP STATUS");
  const backups = bk.list();
  if (backups.length === 0) {
    row("backups", "none",  "WARN");
  } else {
    for (const b of backups.slice(0, 5)) {
      row(b.id, `${b.files.length} file(s) — ${b.reason}`, "PASS");
    }
    if (backups.length > 5) {
      console.log(`  ${clr(C.grey, `  … and ${backups.length - 5} more. Run node tools/doctor.js --all-backups to list all.`)}`);
    }
  }
}

function printBuildReadiness(healthReport) {
  header("BUILD READINESS");
  const ok    = healthReport.healthy;
  const score = healthReport.score;
  if (ok) {
    console.log(`  ${clr(C.green + C.bold, "✅ Ready to build.")}  Score: ${score}/100`);
  } else {
    console.log(`  ${clr(C.red + C.bold, "❌ NOT ready to build.")}  Score: ${score}/100`);
    console.log(`\n  ${clr(C.yellow, "Suggested fixes:")}`);
    for (const checks of Object.values(healthReport.categories)) {
      for (const c of checks) {
        if (c.status === "FAIL") {
          console.log(`    • ${clr(C.red, c.label)}: ${c.detail}`);
        }
      }
    }
    console.log(`\n  Run ${clr(C.cyan, "node tools/repair-engine.cjs")} or ${clr(C.cyan, "npm run heal")} for automatic repair.`);
  }
}

// ── Enhanced diagnostics (production hardening additions) ─────────────────────

function printDiskSpace() {
  header("DISK SPACE");
  try {
    const { execSync } = require("child_process");
    const isWin = process.platform === "win32";
    if (isWin) {
      // wmic is available on all Windows versions
      const out = execSync("wmic logicaldisk get size,freespace,caption", { encoding: "utf8", stdio: "pipe" });
      const lines = out.trim().split("\n").slice(1).filter(Boolean);
      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        if (parts.length >= 3) {
          const drive   = parts[0];
          const free    = parseInt(parts[1], 10);
          const total   = parseInt(parts[2], 10);
          if (!isNaN(free) && !isNaN(total) && total > 0) {
            const freeMb  = Math.round(free / 1024 / 1024);
            const totalMb = Math.round(total / 1024 / 1024);
            const pct     = Math.round((free / total) * 100);
            const status  = pct < 5 ? "FAIL" : pct < 15 ? "WARN" : "PASS";
            row(drive, `${freeMb}MB free of ${totalMb}MB (${pct}%)`, status);
          }
        }
      }
    } else {
      const out = execSync("df -BM . 2>/dev/null | tail -1", { encoding: "utf8", stdio: "pipe" });
      const parts = out.trim().split(/\s+/);
      if (parts.length >= 4) {
        const used  = parts[2];
        const avail = parts[3];
        const pct   = parseInt(parts[4], 10);
        const status = pct > 95 ? "FAIL" : pct > 85 ? "WARN" : "PASS";
        row("current partition", `${avail} free (${pct}% used)`, status);
      }
    }
  } catch (err) {
    row("disk check", `unavailable: ${err.message}`, "WARN");
  }
}

function printNetworkCheck() {
  header("NETWORK");
  const { execSync } = require("child_process");
  const targets = [
    { host: "registry.npmjs.org",   label: "npm registry" },
    { host: "github.com",           label: "GitHub" },
  ];
  const isWin = process.platform === "win32";
  for (const { host, label } of targets) {
    try {
      const cmd = isWin
        ? `ping -n 1 -w 1000 ${host}`
        : `ping -c1 -W1 ${host}`;
      execSync(cmd, { stdio: "ignore", timeout: 4000 });
      row(label, "reachable", "PASS");
    } catch (_) {
      row(label, "unreachable — installs may fail", "WARN");
    }
  }
}

function printEsmCjsCheck(snapshot) {
  header("ESM / CJS COMPATIBILITY");
  try {
    const pkgPath = path.join(ROOT, "package.json");
    if (!fs.existsSync(pkgPath)) {
      row("package.json", "missing", "FAIL");
      return;
    }
    const pkg  = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
    const type = pkg.type || "commonjs";
    row("package.json type", type, "PASS");

    // Warn if .js files use require() in an ESM project
    if (type === "module") {
      const toolFiles = fs.readdirSync(path.join(ROOT, "tools")).filter(f => f.endsWith(".js"));
      if (toolFiles.length > 0) {
        row(".js files in tools/ (ESM project)", `${toolFiles.length} found — should use .cjs`, "WARN");
      } else {
        row(".js files in tools/ (ESM project)", "none (correct)", "PASS");
      }
      // Check node_modules resolution
      const nmExists = fs.existsSync(path.join(ROOT, "node_modules"));
      row("node_modules", nmExists ? "present" : "missing", nmExists ? "PASS" : "WARN");
    }

    // Check for tsconfig module setting
    const tsPath = path.join(ROOT, "tsconfig.json");
    if (fs.existsSync(tsPath)) {
      const ts = JSON.parse(fs.readFileSync(tsPath, "utf8"));
      const mod = (ts.compilerOptions || {}).module || "unknown";
      row("tsconfig module", mod, "PASS");
    }
  } catch (err) {
    row("ESM check", `error: ${err.message}`, "WARN");
  }
}

function printNodeModulesIntegrity() {
  header("NODE_MODULES INTEGRITY");
  const nmPath = path.join(ROOT, "node_modules");
  if (!fs.existsSync(nmPath)) {
    row("node_modules", "missing — run npm install", "FAIL");
    return;
  }

  // Check node_modules/.package-lock.json or package-lock.json match
  const pkgLock = path.join(ROOT, "package-lock.json");
  if (!fs.existsSync(pkgLock)) {
    row("package-lock.json", "missing — lockfile not committed", "WARN");
  } else {
    row("package-lock.json", "present", "PASS");
  }

  // Count top-level dirs as a basic sanity check
  try {
    const entries = fs.readdirSync(nmPath);
    const count   = entries.filter(e => !e.startsWith(".")).length;
    const status  = count < 10 ? "WARN" : "PASS";
    row("package count", `${count} packages`, status);

    // Check for corrupted dirs (0-byte package.json)
    let corrupted = 0;
    for (const entry of entries.slice(0, 200)) {
      const pkgJson = path.join(nmPath, entry, "package.json");
      try {
        const stat = fs.statSync(pkgJson);
        if (stat.size === 0) corrupted++;
      } catch (_) {}
    }
    row("corrupted packages", corrupted > 0 ? `${corrupted} found` : "none detected", corrupted > 0 ? "WARN" : "PASS");
  } catch (err) {
    row("integrity check", `error: ${err.message}`, "WARN");
  }
}

function printTelemetrySnapshot() {
  header("BUILD SYSTEM TELEMETRY");
  try {
    const snap = telemetry.snapshot();
    const c    = snap.counters;
    const r    = snap.rates;
    const a    = snap.averages;
    row("doctor runs",          c.doctor_runs || 0, "PASS");
    row("repair attempts",      c.repair_attempts || 0, "PASS");
    row("repair success rate",  `${((r.repair_success_rate || 0) * 100).toFixed(0)}%`, "PASS");
    row("install success rate", `${((r.install_success_rate || 0) * 100).toFixed(0)}%`, "PASS");
    row("avg build duration",   `${(a.build_duration_ms || 0).toFixed(0)}ms`, "PASS");
  } catch (_) {
    row("telemetry", "unavailable", "WARN");
  }
}

// ── Entry point ────────────────────────────────────────────────────────────────

async function main() {
  const t0 = Date.now();
  bus.emit(bus.EVENTS.DOCTOR_STARTED, { ts: new Date().toISOString() });
  try {
    const [healthReport, snapshot] = await Promise.all([
      health.run(),
      env.snapshot(),
    ]);

    printOverview(snapshot, healthReport);
    printCategories(healthReport);
    await printSnapshot(snapshot);
    printBackups();
    printNodeModulesIntegrity();
    printEsmCjsCheck(snapshot);
    printDiskSpace();
    printNetworkCheck();
    printTelemetrySnapshot();
    printBuildReadiness(healthReport);

    const durationMs = Date.now() - t0;
    telemetry.recordDoctor({ durationMs, healthScore: healthReport.score, healthy: healthReport.healthy });
    bus.emit(bus.EVENTS.DOCTOR_COMPLETED, { durationMs, healthy: healthReport.healthy, score: healthReport.score });

    console.log("");
    const exitCode = healthReport.fails > 0 ? 2 : healthReport.warns > 0 ? 1 : 0;
    process.exit(exitCode);
  } catch (err) {
    const durationMs = Date.now() - t0;
    bus.emit(bus.EVENTS.DOCTOR_COMPLETED, { durationMs, healthy: false, error: err.message });
    console.error(`\n${clr(C.red, "Doctor crashed:")} ${err.message}`);
    if (process.env.DEBUG) console.error(err.stack);
    process.exit(2);
  }
}

main();
