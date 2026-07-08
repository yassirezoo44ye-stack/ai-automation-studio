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

const health = require("./health-check");
const env    = require("./env-checker");
const bk     = require("./backup-manager");

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
    console.log(`\n  Run ${clr(C.cyan, "node tools/repair-engine.js")} or ${clr(C.cyan, "npm run heal")} for automatic repair.`);
  }
}

// ── Entry point ────────────────────────────────────────────────────────────────

async function main() {
  try {
    const [healthReport, snapshot] = await Promise.all([
      health.run(),
      env.snapshot(),
    ]);

    printOverview(snapshot, healthReport);
    printCategories(healthReport);
    await printSnapshot(snapshot);
    printBackups();
    printBuildReadiness(healthReport);

    console.log("");
    const exitCode = healthReport.fails > 0 ? 2 : healthReport.warns > 0 ? 1 : 0;
    process.exit(exitCode);
  } catch (err) {
    console.error(`\n${clr(C.red, "Doctor crashed:")} ${err.message}`);
    if (process.env.DEBUG) console.error(err.stack);
    process.exit(2);
  }
}

main();
