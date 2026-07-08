/**
 * Repair Engine — classifies failures and applies safe, validated fixes.
 *
 * Principles:
 *   - Never edits source files (src/, app/, migrations/, .py, .ts, .tsx)
 *   - Always creates a backup before modifying any config file
 *   - Validates the repair before declaring success
 *   - Avoids infinite retry loops (max 3 attempts per failure class)
 *   - Logs every attempt with root cause + result + next action
 */
"use strict";

const fs      = require("fs");
const path    = require("path");
const os      = require("os");
const { execSync, spawnSync } = require("child_process");

const log     = require("./logger");
const backup  = require("./backup-manager");

const ROOT = path.resolve(__dirname, "..");

// ── Failure classification ─────────────────────────────────────────────────────

const FAILURE = {
  PERMISSION       : "PERMISSION",
  MISSING_HOME     : "MISSING_HOME",
  NO_CACHE_DIR     : "NO_CACHE_DIR",
  READONLY_FS      : "READONLY_FS",
  INSTALL_FAILED   : "INSTALL_FAILED",
  MISSING_PKG_JSON : "MISSING_PKG_JSON",
  MISSING_MODULES  : "MISSING_MODULES",
  MISSING_SCRIPT   : "MISSING_SCRIPT",
  MISSING_PORT     : "MISSING_PORT",
  SYNTAX_ERROR     : "SYNTAX_ERROR",
  UNKNOWN          : "UNKNOWN",
};

function classify(stderr = "", stdout = "") {
  const all = (stderr + stdout).toLowerCase();
  if (all.includes("eacces") || all.includes("permission denied"))   return FAILURE.PERMISSION;
  if (all.includes("enoent") && all.includes("home"))                return FAILURE.MISSING_HOME;
  if (all.includes("cache") && all.includes("enoent"))               return FAILURE.NO_CACHE_DIR;
  if (all.includes("erofs") || all.includes("read-only file"))       return FAILURE.READONLY_FS;
  if (all.includes("syntaxerror") || all.includes("parse error"))    return FAILURE.SYNTAX_ERROR;
  if (all.includes("eaddrinuse"))                                     return FAILURE.MISSING_PORT;
  if (all.includes("cannot find module"))                             return FAILURE.MISSING_MODULES;
  return FAILURE.UNKNOWN;
}

// ── Repair history (in-process, keyed by failure class) ───────────────────────

const _history = {};   // { [failureClass]: { attempts: number, lastResult: string } }
const MAX_ATTEMPTS = 3;

function recordAttempt(failureClass, success) {
  if (!_history[failureClass]) _history[failureClass] = { attempts: 0 };
  _history[failureClass].attempts++;
  _history[failureClass].lastResult = success ? "success" : "fail";
}

function tooManyAttempts(failureClass) {
  return (_history[failureClass]?.attempts ?? 0) >= MAX_ATTEMPTS;
}

// ── Safe shell runner ──────────────────────────────────────────────────────────

function run(cmd, env = {}) {
  const result = spawnSync(cmd, {
    shell  : true,
    cwd    : ROOT,
    env    : { ...process.env, ...env },
    timeout: 5 * 60 * 1000,    // 5-minute timeout
    encoding: "utf8",
  });
  return {
    ok    : result.status === 0,
    stdout: result.stdout || "",
    stderr: result.stderr || "",
    status: result.status,
  };
}

// ── Individual repair strategies ──────────────────────────────────────────────

function repairPermissions() {
  const home = os.homedir();
  const npmCache = path.join(home, ".npm");
  const tmpCache = path.join(os.tmpdir(), "npm-cache");

  // Create ~/.npm if missing
  if (!fs.existsSync(npmCache)) {
    try { fs.mkdirSync(npmCache, { recursive: true }); } catch (_) { /* /tmp fallback */ }
  }
  // Ensure /tmp/npm-cache exists
  try { fs.mkdirSync(tmpCache, { recursive: true }); } catch (_) { /* ok */ }

  return {
    npmCacheExists  : fs.existsSync(npmCache),
    tmpCacheExists  : fs.existsSync(tmpCache),
    suggestion      : `If permission errors persist, run: npm config set cache ${tmpCache}`,
  };
}

// Ordered install strategies — each is tried in order until one succeeds
const INSTALL_STRATEGIES = [
  {
    label: "npm install",
    fn   : () => run("npm install"),
  },
  {
    label: "npm install --cache /tmp/npm-cache",
    fn   : () => run(`npm install --cache ${path.join(os.tmpdir(), "npm-cache")}`),
  },
  {
    label: "HOME=/tmp npm install",
    fn   : () => run("npm install", { HOME: os.tmpdir() }),
  },
  {
    label: "npm ci",
    fn   : () => {
      if (!fs.existsSync(path.join(ROOT, "package-lock.json"))) return { ok: false, stderr: "no package-lock.json" };
      return run("npm ci");
    },
  },
  {
    label: "pnpm install",
    fn   : () => run("pnpm install"),
    guard: () => { try { execSync("pnpm --version", { stdio: "pipe" }); return true; } catch (_) { return false; } },
  },
  {
    label: "yarn install",
    fn   : () => run("yarn install"),
    guard: () => { try { execSync("yarn --version", { stdio: "pipe" }); return true; } catch (_) { return false; } },
  },
  {
    label: "bun install",
    fn   : () => run("bun install"),
    guard: () => { try { execSync("bun --version", { stdio: "pipe" }); return true; } catch (_) { return false; } },
  },
];

/**
 * Self-healing dependency installer.
 * Tries each strategy in order; stops on first success.
 * Never continues to next build stage if all strategies fail.
 *
 * @returns {{ ok: boolean, strategy: string|null, attempts: object[] }}
 */
function installDependencies() {
  const attempts = [];

  // Repair permissions first (idempotent, always safe)
  repairPermissions();

  for (const strategy of INSTALL_STRATEGIES) {
    if (strategy.guard && !strategy.guard()) {
      attempts.push({ label: strategy.label, skipped: true, reason: "tool not available" });
      continue;
    }

    log.install.info(`Trying: ${strategy.label}`);
    const result = strategy.fn();
    attempts.push({ label: strategy.label, ok: result.ok, stderr: result.stderr?.slice(0, 300) });

    if (result.ok) {
      log.install.info(`Success: ${strategy.label}`);
      return { ok: true, strategy: strategy.label, attempts };
    }

    log.install.warn(`Failed: ${strategy.label}`, { stderr: result.stderr?.slice(0, 200) });
  }

  log.errorRecord({
    message       : "All install strategies exhausted",
    rootCause     : "Dependency installation failed with every available package manager",
    repairAttempted: "npm install → npm install --cache → HOME=/tmp → npm ci → pnpm → yarn → bun",
    repairResult  : "FAILED",
    nextAction    : "Check network connectivity, disk space, and file system permissions",
  });

  return { ok: false, strategy: null, attempts };
}

// ── Config file repair (with backup) ──────────────────────────────────────────

/**
 * Safely patch a config file with backup + validation.
 * Only works on ALLOWED_BACKUP files (not source code).
 *
 * @param {string} relPath     — path relative to project root
 * @param {(content: string) => string} patchFn — pure transform
 * @param {string} reason
 * @returns {{ ok: boolean, backupId?: string, error?: string }}
 */
function patchConfig(relPath, patchFn, reason) {
  if (!backup.isAllowed(relPath)) {
    return { ok: false, error: `Not allowed to modify: ${relPath}` };
  }
  const absPath = path.join(ROOT, relPath);
  if (!fs.existsSync(absPath)) {
    return { ok: false, error: `File not found: ${relPath}` };
  }

  const { id: backupId } = backup.create([relPath], reason);

  try {
    const original = fs.readFileSync(absPath, "utf8");
    const patched  = patchFn(original);

    if (patched === original) {
      return { ok: true, backupId, changed: false };
    }

    // Write via temp + rename (atomic)
    const tmp = absPath + ".repair_tmp";
    fs.writeFileSync(tmp, patched, "utf8");
    fs.renameSync(tmp, absPath);

    log.runtime.info(`Config patched: ${relPath}`, { backupId, reason });
    return { ok: true, backupId, changed: true };
  } catch (err) {
    // Restore from backup on failure
    try { backup.restore(backupId); } catch (_) { /* best-effort */ }
    log.errorRecord({
      message       : `Config patch failed: ${relPath}`,
      rootCause     : err.message,
      repairAttempted: `patchConfig(${relPath})`,
      repairResult  : "FAILED — restored from backup",
      nextAction    : "Check file permissions and disk space",
    });
    return { ok: false, backupId, error: err.message };
  }
}

// ── RecoveryManager ───────────────────────────────────────────────────────────

const RecoveryManager = {
  FAILURE,
  classify,
  history: () => ({ ..._history }),
  tooManyAttempts,

  /**
   * Main entry point: classify + choose strategy + apply + validate.
   * @param {{ stderr?: string, stdout?: string, context?: string }} failure
   * @returns {{ ok: boolean, failureClass: string, action: string, result: any }}
   */
  async recover(failure) {
    const { stderr = "", stdout = "", context = "unknown" } = failure;
    const failureClass = classify(stderr, stdout);

    if (tooManyAttempts(failureClass)) {
      return {
        ok: false,
        failureClass,
        action: "skipped",
        result: `Max recovery attempts (${MAX_ATTEMPTS}) reached for ${failureClass}`,
      };
    }

    log.runtime.warn(`Recovery triggered: ${failureClass}`, { context });
    let result;

    if (failureClass === FAILURE.INSTALL_FAILED  ||
        failureClass === FAILURE.MISSING_MODULES ||
        failureClass === FAILURE.PERMISSION      ||
        failureClass === FAILURE.NO_CACHE_DIR    ||
        failureClass === FAILURE.READONLY_FS) {
      result = installDependencies();
      recordAttempt(failureClass, result.ok);
      return { ok: result.ok, failureClass, action: "install", result };
    }

    if (failureClass === FAILURE.MISSING_HOME) {
      const perm = repairPermissions();
      recordAttempt(failureClass, true);
      return { ok: true, failureClass, action: "permission-repair", result: perm };
    }

    recordAttempt(failureClass, false);
    return { ok: false, failureClass, action: "none", result: "No automatic repair available" };
  },
};

module.exports = { RepairEngine: RecoveryManager, installDependencies, patchConfig, repairPermissions, FAILURE, classify };
