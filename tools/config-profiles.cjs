"use strict";
/**
 * Configuration profiles for the build system.
 * Profiles: development | testing | staging | production
 *
 * Each profile overrides only supported settings; all other values fall back
 * to the defaults. The active profile is resolved from:
 *   1. Explicit argument to getConfig(profile)
 *   2. BUILD_PROFILE environment variable
 *   3. NODE_ENV → "testing" if "test", else default to "development"
 *
 * @module config-profiles
 */

// ── Default configuration ─────────────────────────────────────────────────────

/**
 * @typedef {Object} BuildConfig
 * @property {string}  profile              Active profile name
 * @property {boolean} verbose              Log all command output
 * @property {number}  maxRepairAttempts    Global retry cap for repair
 * @property {number}  installTimeoutMs     Install command timeout
 * @property {number}  healthTimeoutMs      Health check timeout
 * @property {number}  doctorTimeoutMs      Doctor run timeout
 * @property {boolean} autoRollback         Roll back automatically on failure
 * @property {boolean} requireLockfile      Fail install if no lockfile present
 * @property {boolean} metricsEnabled       Expose Prometheus metrics endpoint
 * @property {number}  metricsPort          Port for metrics HTTP server
 * @property {boolean} tracingEnabled       Emit OpenTelemetry-style spans
 * @property {boolean} sandboxStrict        Abort on sandbox violations (vs. warn)
 * @property {boolean} concurrencyGuard     Enable file-lock concurrency protection
 * @property {string[]} pluginDirs          Directories to scan for plugins
 * @property {boolean} colorOutput          ANSI colour in CLI output
 * @property {boolean} persistTelemetry     Write telemetry to logs/telemetry.jsonl
 */

/** @type {BuildConfig} */
const DEFAULTS = {
  profile           : "development",
  verbose           : false,
  maxRepairAttempts : 3,
  installTimeoutMs  : 120_000,
  healthTimeoutMs   : 30_000,
  doctorTimeoutMs   : 10_000,
  autoRollback      : true,
  requireLockfile   : false,
  metricsEnabled    : false,
  metricsPort       : 9091,
  tracingEnabled    : true,
  sandboxStrict     : true,
  concurrencyGuard  : true,
  pluginDirs        : ["./tools/plugins"],
  colorOutput       : true,
  persistTelemetry  : true,
};

// ── Profile overrides ─────────────────────────────────────────────────────────

/** @type {Record<string, Partial<BuildConfig>>} */
const PROFILES = {
  development: {
    verbose         : true,
    metricsEnabled  : false,
    requireLockfile : false,
    sandboxStrict   : false,  // lenient in dev — warn instead of abort
    colorOutput     : true,
  },

  testing: {
    verbose          : false,
    maxRepairAttempts: 1,
    installTimeoutMs : 60_000,
    healthTimeoutMs  : 5_000,
    doctorTimeoutMs  : 3_000,
    autoRollback     : false,  // tests assert on failure, not on recovery
    metricsEnabled   : false,
    tracingEnabled   : false,
    sandboxStrict    : true,
    concurrencyGuard : false,  // tests run in process, no file locks needed
    persistTelemetry : false,
    colorOutput      : false,
  },

  staging: {
    verbose          : true,
    maxRepairAttempts: 2,
    metricsEnabled   : true,
    requireLockfile  : true,
    sandboxStrict    : true,
    colorOutput      : false,
    persistTelemetry : true,
  },

  production: {
    verbose          : false,
    maxRepairAttempts: 2,
    installTimeoutMs : 90_000,
    healthTimeoutMs  : 10_000,
    doctorTimeoutMs  : 5_000,
    autoRollback     : true,
    requireLockfile  : true,
    metricsEnabled   : true,
    tracingEnabled   : true,
    sandboxStrict    : true,
    concurrencyGuard : true,
    colorOutput      : false,
    persistTelemetry : true,
  },
};

// ── Active profile detection ──────────────────────────────────────────────────

/**
 * Resolve the active profile name from env.
 *
 * @returns {string}
 */
function detectProfile() {
  const env = (process.env.BUILD_PROFILE || "").toLowerCase();
  if (PROFILES[env]) return env;
  const node = (process.env.NODE_ENV || "").toLowerCase();
  if (node === "test" || node === "testing") return "testing";
  if (node === "production")                 return "production";
  if (node === "staging")                    return "staging";
  return "development";
}

// ── Cache ─────────────────────────────────────────────────────────────────────

const _cache = new Map();

/**
 * Get the merged configuration for a profile.
 * Results are cached per profile name.
 *
 * @param {string} [profile]   Explicit profile name; defaults to auto-detect
 * @returns {BuildConfig}
 */
function getConfig(profile) {
  profile = profile || detectProfile();
  if (_cache.has(profile)) return _cache.get(profile);

  const overrides = PROFILES[profile] || PROFILES.development;
  const cfg       = Object.assign({}, DEFAULTS, overrides, { profile });

  _cache.set(profile, cfg);
  return cfg;
}

/**
 * List all available profile names.
 *
 * @returns {string[]}
 */
function listProfiles() {
  return Object.keys(PROFILES);
}

/**
 * Return the diff between a profile and defaults
 * (what the profile actually changes).
 *
 * @param {string} profile
 * @returns {Partial<BuildConfig>}
 */
function profileDiff(profile) {
  return PROFILES[profile] || {};
}

/**
 * Clear the config cache (useful in tests that manipulate env vars).
 */
function clearCache() {
  _cache.clear();
}

module.exports = { getConfig, detectProfile, listProfiles, profileDiff, clearCache };
