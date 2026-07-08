"use strict";
/**
 * Package manager abstraction layer.
 * Auto-detects npm / pnpm / yarn / bun via lockfile-first strategy,
 * then provides a unified interface: install(), ci(), add(), remove(), run().
 *
 * @module pm-abstraction
 */
const { execSync, spawnSync } = require("child_process");
const fs   = require("fs");
const path = require("path");

// ── Detection ─────────────────────────────────────────────────────────────────

/**
 * @typedef {"npm"|"pnpm"|"yarn"|"bun"} PackageManager
 */

/** @type {Record<string, PackageManager>} lockfile → pm */
const LOCKFILE_MAP = {
  "pnpm-lock.yaml" : "pnpm",
  "yarn.lock"      : "yarn",
  "bun.lockb"      : "bun",
  "package-lock.json" : "npm",
};

/**
 * Probe whether a binary exists on PATH.
 * @param {string} bin
 * @returns {boolean}
 */
function _probe(bin) {
  try {
    const isWin = process.platform === "win32";
    const cmd   = isWin ? `where ${bin}` : `which ${bin}`;
    execSync(cmd, { stdio: "ignore", timeout: 3000 });
    return true;
  } catch (_) { return false; }
}

/**
 * Detect the project's package manager.
 *
 * Priority: lockfile in cwd > lockfile in packageJson.packageManager > probe > npm
 *
 * @param {string} [cwd]   Project directory (defaults to process.cwd())
 * @returns {PackageManager}
 */
function detect(cwd) {
  cwd = cwd || process.cwd();

  // 1. Lockfile-first
  for (const [lf, pm] of Object.entries(LOCKFILE_MAP)) {
    if (fs.existsSync(path.join(cwd, lf))) return pm;
  }

  // 2. packageManager field in package.json
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(cwd, "package.json"), "utf8"));
    if (pkg.packageManager) {
      const name = pkg.packageManager.split("@")[0].trim().toLowerCase();
      if (["npm", "pnpm", "yarn", "bun"].includes(name)) return name;
    }
  } catch (_) {}

  // 3. Probe
  for (const pm of ["pnpm", "yarn", "bun", "npm"]) {
    if (_probe(pm)) return pm;
  }

  return "npm";
}

// ── Command maps ──────────────────────────────────────────────────────────────

/** @type {Record<PackageManager, Record<string, string|string[]>>} */
const COMMANDS = {
  npm : {
    install : ["npm", "install"],
    ci      : ["npm", "ci"],
    add     : (pkgs) => ["npm", "install", "--save", ...pkgs],
    remove  : (pkgs) => ["npm", "uninstall", ...pkgs],
    run     : (script, args) => ["npm", "run", script, ...(args || [])],
    exec    : (bin, args) => ["npx", "--yes", bin, ...(args || [])],
  },
  pnpm: {
    install : ["pnpm", "install"],
    ci      : ["pnpm", "install", "--frozen-lockfile"],
    add     : (pkgs) => ["pnpm", "add", ...pkgs],
    remove  : (pkgs) => ["pnpm", "remove", ...pkgs],
    run     : (script, args) => ["pnpm", "run", script, ...(args || [])],
    exec    : (bin, args) => ["pnpm", "exec", bin, ...(args || [])],
  },
  yarn: {
    install : ["yarn", "install"],
    ci      : ["yarn", "install", "--frozen-lockfile"],
    add     : (pkgs) => ["yarn", "add", ...pkgs],
    remove  : (pkgs) => ["yarn", "remove", ...pkgs],
    run     : (script, args) => ["yarn", "run", script, ...(args || [])],
    exec    : (bin, args) => ["yarn", "exec", bin, ...(args || [])],
  },
  bun : {
    install : ["bun", "install"],
    ci      : ["bun", "install", "--frozen-lockfile"],
    add     : (pkgs) => ["bun", "add", ...pkgs],
    remove  : (pkgs) => ["bun", "remove", ...pkgs],
    run     : (script, args) => ["bun", "run", script, ...(args || [])],
    exec    : (bin, args) => ["bunx", bin, ...(args || [])],
  },
};

// ── Execution ─────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} RunResult
 * @property {boolean} ok
 * @property {number}  code
 * @property {string}  stdout
 * @property {string}  stderr
 * @property {string}  cmd
 * @property {number}  durationMs
 */

/**
 * Execute a command array with optional environment overrides.
 *
 * @param {string[]} argv
 * @param {Object}   [opts]
 * @param {string}   [opts.cwd]
 * @param {Object}   [opts.env]
 * @param {number}   [opts.timeout=120000]
 * @returns {RunResult}
 */
function _exec(argv, opts) {
  opts = opts || {};
  const t0 = Date.now();
  const result = spawnSync(argv[0], argv.slice(1), {
    cwd    : opts.cwd || process.cwd(),
    env    : { ...process.env, ...(opts.env || {}) },
    timeout: opts.timeout || 120_000,
    encoding: "utf8",
  });
  return {
    ok        : result.status === 0,
    code      : result.status || 0,
    stdout    : result.stdout || "",
    stderr    : result.stderr || "",
    cmd       : argv.join(" "),
    durationMs: Date.now() - t0,
  };
}

// ── PM facade ─────────────────────────────────────────────────────────────────

/**
 * Create a package-manager facade for the given directory.
 *
 * @param {string} [cwd]
 * @returns {PMFacade}
 */
function createPM(cwd) {
  cwd = cwd || process.cwd();
  const pm  = detect(cwd);
  const cmds = COMMANDS[pm];

  /**
   * @typedef {Object} PMFacade
   */
  return {
    /** Which package manager was detected */
    name: pm,

    /**
     * Install all dependencies (respects existing lockfile).
     * @param {Object} [opts]
     * @returns {RunResult}
     */
    install(opts) {
      return _exec(cmds.install, { cwd, ...opts });
    },

    /**
     * Clean install (requires lockfile, fails if versions differ).
     * @param {Object} [opts]
     * @returns {RunResult}
     */
    ci(opts) {
      return _exec(cmds.ci, { cwd, ...opts });
    },

    /**
     * Add one or more packages.
     * @param {string|string[]} pkgs
     * @param {Object} [opts]
     * @returns {RunResult}
     */
    add(pkgs, opts) {
      const names = Array.isArray(pkgs) ? pkgs : [pkgs];
      return _exec(cmds.add(names), { cwd, ...opts });
    },

    /**
     * Remove one or more packages.
     * @param {string|string[]} pkgs
     * @param {Object} [opts]
     * @returns {RunResult}
     */
    remove(pkgs, opts) {
      const names = Array.isArray(pkgs) ? pkgs : [pkgs];
      return _exec(cmds.remove(names), { cwd, ...opts });
    },

    /**
     * Run a package.json script.
     * @param {string}   script
     * @param {string[]} [args]
     * @param {Object}   [opts]
     * @returns {RunResult}
     */
    run(script, args, opts) {
      return _exec(cmds.run(script, args), { cwd, ...opts });
    },

    /**
     * Execute a local binary (npx / pnpm exec / yarn exec / bunx).
     * @param {string}   bin
     * @param {string[]} [args]
     * @param {Object}   [opts]
     * @returns {RunResult}
     */
    exec(bin, args, opts) {
      return _exec(cmds.exec(bin, args), { cwd, ...opts });
    },
  };
}

module.exports = { detect, createPM };
