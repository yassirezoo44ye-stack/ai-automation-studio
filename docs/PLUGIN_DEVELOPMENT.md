# Plugin Development Guide

The build system supports four plugin types that let you extend its behaviour without modifying core files.

## Plugin Types

| Type | Purpose | Key methods |
|---|---|---|
| `repair` | Custom failure classifier and recovery handler | `classify(stderr, stdout)`, `recover(failure, context)` |
| `health` | Additional health probes shown in doctor output | `check()` |
| `doctor` | Additional diagnostic sections | `run()` |
| `installer` | Alternative package installation strategies | `guard()`, `install()` |

## Creating a Plugin

A plugin is a CJS file (`.cjs` extension) that exports a `register(api)` function:

```js
// tools/plugins/my-custom-check.cjs
"use strict";

module.exports = {
  register(api) {
    api.register({
      name    : "my-custom-check",
      type    : "health",
      category: "custom",
      async check() {
        // Your check logic here
        const ok = someCheck();
        return {
          status : ok ? "PASS" : "WARN",
          message: ok ? "all good" : "something is off",
        };
      },
    });
  },
};
```

## Loading Plugins

Plugins are loaded from directories listed in the config profile's `pluginDirs` field (default: `["./tools/plugins"]`). Place your plugin file in that directory and it will be picked up automatically.

To load programmatically:

```js
const plugins = require("./tools/plugins.cjs");
plugins.loadDir("./my-plugin-dir");
```

## Repair Plugin Reference

```js
api.register({
  name    : "my-repair",
  type    : "repair",
  /**
   * Classify a build failure from its stderr/stdout output.
   * Return a FAILURE.* constant string, or null if this plugin doesn't handle it.
   */
  classify(stderr, stdout) {
    if (/EACCES/.test(stderr)) return "PERMISSION";
    return null;
  },
  /**
   * Attempt to recover from a classified failure.
   * @param {string} failure   The FAILURE.* code
   * @param {Object} context   { stderr, stdout }
   * @returns {Promise<{ ok: boolean, message: string }>}
   */
  async recover(failure, context) {
    if (failure !== "PERMISSION") return { ok: false, message: "not my failure" };
    // ... fix permissions ...
    return { ok: true, message: "permissions fixed" };
  },
});
```

## Health Plugin Reference

```js
api.register({
  name    : "redis-check",
  type    : "health",
  category: "services",
  async check() {
    try {
      // ... probe redis ...
      return { status: "PASS", message: "Redis reachable on :6379" };
    } catch (err) {
      return { status: "WARN", message: `Redis unavailable: ${err.message}` };
    }
  },
});
```

## Doctor Plugin Reference

```js
api.register({
  name : "env-audit",
  type : "doctor",
  title: "ENVIRONMENT AUDIT",
  async run() {
    return [
      "  ✅ SECRET_KEY is set",
      "  ⚠️  SENTRY_DSN not set — errors will not be reported",
    ];
  },
});
```

## Installer Plugin Reference

```js
api.register({
  name   : "volta-installer",
  type   : "installer",
  /** Return true if this installer is available on the system */
  guard() {
    const { execSync } = require("child_process");
    try { execSync("volta --version", { stdio: "ignore" }); return true; }
    catch (_) { return false; }
  },
  async install() {
    const { spawnSync } = require("child_process");
    const r = spawnSync("volta", ["install", "node"], { encoding: "utf8" });
    return { ok: r.status === 0, stdout: r.stdout, stderr: r.stderr };
  },
});
```

## Plugin Isolation

Plugins run inside a `try/catch` — a crashing plugin never brings down the build system. Failed plugin loads are reported in `loadDir()`'s return value:

```js
const { loaded, failed } = plugins.loadDir("./my-plugins");
console.log("Loaded:", loaded);
console.log("Failed:", failed);  // [{ file, error }]
```

## Security Notes

- Plugins are loaded with `require()`, giving them full Node.js access. Only load plugins you trust.
- Repair plugins must respect the **sandbox** (no writes outside the allowlist).
- Health and doctor plugins should be read-only.
