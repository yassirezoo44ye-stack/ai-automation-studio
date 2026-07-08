"use strict";
/**
 * Plugin architecture for the Self-Healing Build System.
 *
 * Plugin types:
 *   repair    — custom failure handlers (classify + recover)
 *   health    — additional health check probes
 *   doctor    — additional doctor output sections
 *   installer — alternative install strategies
 *
 * Each plugin is a CJS module exporting a `register(api)` function.
 * Plugins run in isolated try/catch — one bad plugin never crashes the system.
 *
 * @module plugins
 */
const fs   = require("fs");
const path = require("path");

// ── Plugin type definitions ───────────────────────────────────────────────────

/**
 * @typedef {"repair"|"health"|"doctor"|"installer"} PluginType
 */

/**
 * @typedef {Object} RepairPlugin
 * @property {string}   name
 * @property {string}   type       "repair"
 * @property {Function} classify   (stderr, stdout) => string|null  — return failure code or null
 * @property {Function} recover    async (failure, context) => {ok, message}
 */

/**
 * @typedef {Object} HealthPlugin
 * @property {string}   name
 * @property {string}   type      "health"
 * @property {string}   category  Category label shown in health output
 * @property {Function} check     async () => {status: "PASS"|"WARN"|"FAIL", message}
 */

/**
 * @typedef {Object} DoctorPlugin
 * @property {string}   name
 * @property {string}   type      "doctor"
 * @property {string}   title     Section title
 * @property {Function} run       async () => string[]  — lines to print
 */

/**
 * @typedef {Object} InstallerPlugin
 * @property {string}   name
 * @property {string}   type      "installer"
 * @property {Function} guard     () => boolean  — true if this installer is available
 * @property {Function} install   async () => {ok, stdout, stderr}
 */

// ── Registry ──────────────────────────────────────────────────────────────────

/** @type {Map<string, RepairPlugin|HealthPlugin|DoctorPlugin|InstallerPlugin>} */
const _plugins = new Map();

/**
 * @typedef {Object} PluginAPI
 * @property {Function} register  Register a plugin object
 */

const _api = {
  /**
   * Register a plugin.
   * @param {Object} plugin
   */
  register(plugin) {
    if (!plugin || !plugin.name || !plugin.type) {
      throw new Error("Plugin must have `name` and `type` fields");
    }
    _plugins.set(plugin.name, plugin);
  },
};

// ── Loader ────────────────────────────────────────────────────────────────────

/**
 * Load all plugins from a directory.
 * Each .cjs or .js file is require()'d and its exported `register(api)` is called.
 *
 * @param {string} dir  Absolute or relative path to plugin directory
 * @returns {{loaded: string[], failed: {file: string, error: string}[]}}
 */
function loadDir(dir) {
  const absDir  = path.resolve(dir);
  const loaded  = [];
  const failed  = [];

  if (!fs.existsSync(absDir)) return { loaded, failed };

  const files = fs.readdirSync(absDir).filter(f => f.endsWith(".cjs") || f.endsWith(".js"));

  for (const file of files) {
    const fullPath = path.join(absDir, file);
    try {
      const mod = require(fullPath);
      if (typeof mod.register === "function") {
        mod.register(_api);
        loaded.push(file);
      } else {
        failed.push({ file, error: "missing export: register(api)" });
      }
    } catch (err) {
      failed.push({ file, error: err.message });
    }
  }

  return { loaded, failed };
}

/**
 * Load plugins from a list of directories.
 *
 * @param {string[]} dirs
 * @returns {{loaded: string[], failed: Array}}
 */
function loadDirs(dirs) {
  const result = { loaded: [], failed: [] };
  for (const dir of dirs) {
    const r = loadDir(dir);
    result.loaded.push(...r.loaded);
    result.failed.push(...r.failed);
  }
  return result;
}

// ── Plugin queries ────────────────────────────────────────────────────────────

/**
 * Get all plugins of a specific type.
 *
 * @param {PluginType} type
 * @returns {Array}
 */
function getPlugins(type) {
  return [..._plugins.values()].filter(p => p.type === type);
}

/**
 * Get a plugin by name.
 *
 * @param {string} name
 * @returns {Object|undefined}
 */
function getPlugin(name) {
  return _plugins.get(name);
}

/**
 * Return all registered plugins and their metadata.
 *
 * @returns {Array<{name: string, type: string}>}
 */
function listPlugins() {
  return [..._plugins.values()].map(p => ({ name: p.name, type: p.type }));
}

/**
 * Unregister a plugin by name (useful in tests).
 *
 * @param {string} name
 */
function unregister(name) {
  _plugins.delete(name);
}

/**
 * Clear all registered plugins (useful in tests).
 */
function clearAll() {
  _plugins.clear();
}

// ── Safe plugin runners ───────────────────────────────────────────────────────

/**
 * Run all repair plugins' classify() against stderr/stdout.
 * Returns the first non-null classification.
 *
 * @param {string} stderr
 * @param {string} stdout
 * @returns {string|null}
 */
function classifyWithPlugins(stderr, stdout) {
  for (const plugin of getPlugins("repair")) {
    try {
      const code = plugin.classify(stderr, stdout);
      if (code) return code;
    } catch (_) {}
  }
  return null;
}

/**
 * Run all repair plugins' recover() for a given failure.
 * Returns on first success.
 *
 * @param {string} failure   FAILURE.* constant
 * @param {Object} context
 * @returns {Promise<{ok: boolean, message: string, plugin?: string}|null>}
 */
async function recoverWithPlugins(failure, context) {
  for (const plugin of getPlugins("repair")) {
    try {
      const r = await plugin.recover(failure, context);
      if (r && r.ok) return { ...r, plugin: plugin.name };
    } catch (_) {}
  }
  return null;
}

/**
 * Run all health plugins and return their results.
 *
 * @returns {Promise<Array<{name: string, category: string, status: string, message: string}>>}
 */
async function runHealthPlugins() {
  const results = [];
  for (const plugin of getPlugins("health")) {
    try {
      const r = await plugin.check();
      results.push({ name: plugin.name, category: plugin.category, ...r });
    } catch (err) {
      results.push({ name: plugin.name, category: plugin.category, status: "FAIL", message: err.message });
    }
  }
  return results;
}

/**
 * Run all doctor plugins and return their output lines.
 *
 * @returns {Promise<Array<{title: string, lines: string[]}>>}
 */
async function runDoctorPlugins() {
  const sections = [];
  for (const plugin of getPlugins("doctor")) {
    try {
      const lines = await plugin.run();
      sections.push({ title: plugin.title, lines: lines || [] });
    } catch (err) {
      sections.push({ title: plugin.title, lines: [`Error: ${err.message}`] });
    }
  }
  return sections;
}

/**
 * Get available installer plugins (those whose guard() returns true).
 *
 * @returns {InstallerPlugin[]}
 */
function availableInstallers() {
  return getPlugins("installer").filter(p => {
    try { return p.guard(); } catch (_) { return false; }
  });
}

module.exports = {
  loadDir,
  loadDirs,
  getPlugins,
  getPlugin,
  listPlugins,
  unregister,
  clearAll,
  classifyWithPlugins,
  recoverWithPlugins,
  runHealthPlugins,
  runDoctorPlugins,
  availableInstallers,
  _api,
};
