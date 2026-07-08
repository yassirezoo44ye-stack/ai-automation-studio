"use strict";
/**
 * Sandbox: path validation layer preventing the build system from writing
 * outside the project root, touching source code, modifying git history,
 * or deleting user files.
 *
 * Every write operation performed by repair/recovery must pass through
 * sandbox.assertWritable(targetPath) before proceeding.
 *
 * @module sandbox
 */
const fs   = require("fs");
const path = require("path");

// ── Root ──────────────────────────────────────────────────────────────────────

const PROJECT_ROOT = path.resolve(process.cwd());

// ── Protected path patterns (regex on the relative path) ─────────────────────

const PROTECTED_PATTERNS = [
  /^src\//,          // frontend source
  /^app\//,          // Python backend source
  /^migrations\//,   // Alembic migrations
  /^alembic\//,
  /^\.git\//,        // git history (NEVER touch)
  /^\.github\//,     // CI workflows
  /^tests\//,        // test suite
  /^docs\//,         // documentation
  /\.py$/,           // any Python file
  /\.ts$/,           /\.tsx$/,           // TypeScript source
  /\.jsx?$/,         // JS source (allow .cjs/.mjs separately)
  /Dockerfile/,
  /render\.yaml/,
  /\.pem$/, /\.key$/, /\.p12$/, /id_rsa/, /id_ed25519/,
  /\.env$/,          // .env at root is writable only through backup-manager
];

// ── Files the build system IS allowed to write ───────────────────────────────

const ALLOWED_WRITES = new Set([
  "package.json",
  "package-lock.json",
  ".npmrc",
  ".nvmrc",
  ".node-version",
  "vite.config.ts",
  "vite.config.js",
  "tsconfig.json",
  "tsconfig.node.json",
  ".env.local",
  ".env.development",
  "eslint.config.js",
  "eslint.config.mjs",
]);

// Allowed directories (relative)
const ALLOWED_DIRS = [
  "logs/",
  ".locks/",
  "backups/",
  "node_modules/",   // the installer writes here
];

// ── Validation ────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} SandboxResult
 * @property {boolean} allowed
 * @property {string}  [reason]   Why it was blocked
 * @property {string}  absPath    Resolved absolute path
 * @property {string}  relPath    Relative-to-root path
 */

/**
 * Check whether a path is writable by the build system.
 *
 * @param {string} targetPath  Absolute or relative path
 * @returns {SandboxResult}
 */
function check(targetPath) {
  const abs = path.resolve(PROJECT_ROOT, targetPath);
  const rel = path.relative(PROJECT_ROOT, abs).replace(/\\/g, "/");

  // 1. Must stay within project root
  if (rel.startsWith("..")) {
    return { allowed: false, reason: "path escapes project root", absPath: abs, relPath: rel };
  }

  // 2. Explicitly allowed directories
  for (const dir of ALLOWED_DIRS) {
    if (rel.startsWith(dir) || rel === dir.replace(/\/$/, "")) {
      return { allowed: true, absPath: abs, relPath: rel };
    }
  }

  // 3. Explicitly allowed files (exact match)
  const basename = path.basename(rel);
  if (ALLOWED_WRITES.has(basename) && !rel.includes("/")) {
    return { allowed: true, absPath: abs, relPath: rel };
  }

  // 4. Check protected patterns
  for (const pat of PROTECTED_PATTERNS) {
    if (pat.test(rel)) {
      return { allowed: false, reason: `matches protected pattern ${pat}`, absPath: abs, relPath: rel };
    }
  }

  return { allowed: false, reason: "not in allowlist", absPath: abs, relPath: rel };
}

/**
 * Assert that `targetPath` is writable.
 * Throws a descriptive error if not.
 *
 * @param {string} targetPath
 * @throws {Error} if path is not writable
 */
function assertWritable(targetPath) {
  const result = check(targetPath);
  if (!result.allowed) {
    throw new Error(
      `[sandbox] Write blocked: "${result.relPath}" — ${result.reason}. ` +
      "The build system may not modify source files."
    );
  }
}

/**
 * Safely read any file (reads are unrestricted within the project).
 *
 * @param {string} targetPath
 * @returns {{ok: boolean, content?: string, error?: string}}
 */
function safeRead(targetPath) {
  const abs = path.resolve(PROJECT_ROOT, targetPath);
  const rel = path.relative(PROJECT_ROOT, abs);
  if (rel.startsWith("..")) {
    return { ok: false, error: "path escapes project root" };
  }
  try {
    return { ok: true, content: fs.readFileSync(abs, "utf8") };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

/**
 * Safely write a file — runs sandbox check first.
 *
 * @param {string} targetPath
 * @param {string} content
 * @returns {{ok: boolean, error?: string, blocked?: boolean}}
 */
function safeWrite(targetPath, content) {
  const { allowed, reason, absPath } = check(targetPath);
  if (!allowed) return { ok: false, blocked: true, error: reason };
  try {
    fs.mkdirSync(path.dirname(absPath), { recursive: true });
    fs.writeFileSync(absPath, content, "utf8");
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

/**
 * List all allowed writable paths (for documentation / doctor output).
 *
 * @returns {{files: string[], dirs: string[]}}
 */
function allowedPaths() {
  return {
    files: [...ALLOWED_WRITES],
    dirs : [...ALLOWED_DIRS],
  };
}

module.exports = { check, assertWritable, safeRead, safeWrite, allowedPaths, PROJECT_ROOT };
