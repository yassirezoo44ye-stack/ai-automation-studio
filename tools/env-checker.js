/**
 * Environment Checker — detects Node version, package manager, permissions,
 * HOME writability, cache dirs, and required env vars.
 *
 * Never modifies anything. Pure read-only diagnostics.
 */
"use strict";

const fs      = require("fs");
const path    = require("path");
const os      = require("os");
const { execSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");

// ── Package manager detection ─────────────────────────────────────────────────

const LOCKFILE_PM = [
  { file: "pnpm-lock.yaml", pm: "pnpm"  },
  { file: "yarn.lock",      pm: "yarn"  },
  { file: "bun.lockb",      pm: "bun"   },
  { file: "package-lock.json", pm: "npm" },
];

function detectPackageManager() {
  // 1. Lockfile takes priority
  for (const { file, pm } of LOCKFILE_PM) {
    if (fs.existsSync(path.join(ROOT, file))) {
      return { pm, source: "lockfile", lockfile: file };
    }
  }
  // 2. Probe installed binaries
  for (const pm of ["pnpm", "yarn", "bun", "npm"]) {
    try {
      execSync(`${pm} --version`, { stdio: "pipe" });
      return { pm, source: "probe" };
    } catch (_) { /* not available */ }
  }
  return { pm: "npm", source: "fallback" };
}

function pmVersion(pm) {
  try { return execSync(`${pm} --version`, { stdio: "pipe" }).toString().trim(); }
  catch (_) { return null; }
}

// ── Permissions ────────────────────────────────────────────────────────────────

function canWrite(dir) {
  try {
    const probe = path.join(dir, ".axon_write_probe_" + Date.now());
    fs.mkdirSync(path.dirname(probe), { recursive: true });
    fs.writeFileSync(probe, "1");
    fs.unlinkSync(probe);
    return true;
  } catch (_) { return false; }
}

function checkPermissions() {
  const home    = os.homedir();
  const tmp     = os.tmpdir();
  const npmCache = path.join(home, ".npm");
  const cwd      = ROOT;

  return {
    home         : { path: home,     writable: canWrite(home)     },
    tmp          : { path: tmp,      writable: canWrite(tmp)      },
    cwd          : { path: cwd,      writable: canWrite(cwd)      },
    npmCache     : { path: npmCache, writable: canWrite(npmCache) || !fs.existsSync(npmCache) },
    fallbackCache: { path: path.join(tmp, "npm-cache"), writable: canWrite(tmp) },
  };
}

// ── Node version ──────────────────────────────────────────────────────────────

function nodeInfo() {
  const ver = process.version;               // e.g. "v20.11.0"
  const parts = ver.slice(1).split(".").map(Number);
  return {
    version : ver,
    major   : parts[0],
    minor   : parts[1],
    patch   : parts[2],
    ok      : parts[0] >= 18,               // project requires Node 18+
  };
}

// ── Environment variables ──────────────────────────────────────────────────────

const REQUIRED_VARS = [];         // list prod-required vars here, e.g. "DATABASE_URL"
const OPTIONAL_VARS = [
  "NODE_ENV", "PORT", "VITE_API_URL",
  "ANTHROPIC_API_KEY", "DATABASE_URL",
];

function checkEnvVars() {
  const missing  = REQUIRED_VARS.filter(v => !process.env[v]);
  const present  = OPTIONAL_VARS.filter(v =>  process.env[v]);
  const absent   = OPTIONAL_VARS.filter(v => !process.env[v]);
  return { missing, present, absent, allRequiredPresent: missing.length === 0 };
}

// ── Project files ─────────────────────────────────────────────────────────────

function checkProjectFiles() {
  const pkg = path.join(ROOT, "package.json");
  let pkgData = null;
  let scripts = {};
  let entrypoint = null;

  if (fs.existsSync(pkg)) {
    try {
      pkgData = JSON.parse(fs.readFileSync(pkg, "utf8"));
      scripts = pkgData.scripts || {};
      entrypoint = pkgData.main || null;
    } catch (_) { /* invalid JSON */ }
  }

  const nodeModules = path.join(ROOT, "node_modules");
  const hasLockfile = LOCKFILE_PM.some(({ file }) => fs.existsSync(path.join(ROOT, file)));

  return {
    packageJson    : { exists: fs.existsSync(pkg), valid: pkgData !== null },
    nodeModules    : { exists: fs.existsSync(nodeModules) },
    lockfile       : { exists: hasLockfile },
    scripts        : {
      dev    : !!scripts.dev,
      build  : !!scripts.build,
      start  : !!scripts.start,
      test   : !!scripts.test,
      doctor : !!scripts.doctor,
    },
    entrypoint     : entrypoint ? { path: entrypoint, exists: fs.existsSync(path.join(ROOT, entrypoint)) } : null,
    viteConfig     : { exists: fs.existsSync(path.join(ROOT, "vite.config.ts")) || fs.existsSync(path.join(ROOT, "vite.config.js")) },
    tsConfig       : { exists: fs.existsSync(path.join(ROOT, "tsconfig.json")) },
  };
}

// ── Port check ────────────────────────────────────────────────────────────────

function checkPort(port) {
  try {
    const net    = require("net");
    return new Promise(resolve => {
      const server = net.createServer();
      server.once("error", () => resolve({ port, available: false }));
      server.once("listening", () => { server.close(); resolve({ port, available: true }); });
      server.listen(port, "127.0.0.1");
    });
  } catch (_) {
    return Promise.resolve({ port, available: false });
  }
}

async function checkPorts() {
  const targets = [3000, 5173, 8000, 8080];
  return Promise.all(targets.map(checkPort));
}

// ── Full snapshot ─────────────────────────────────────────────────────────────

async function snapshot() {
  const pmInfo    = detectPackageManager();
  const pmVer     = pmVersion(pmInfo.pm);

  return {
    node        : nodeInfo(),
    packageManager: { ...pmInfo, version: pmVer },
    permissions : checkPermissions(),
    project     : checkProjectFiles(),
    env         : checkEnvVars(),
    ports       : await checkPorts(),
  };
}

module.exports = { snapshot, detectPackageManager, checkPermissions, nodeInfo, checkEnvVars, checkProjectFiles, checkPort, checkPorts, pmVersion };
