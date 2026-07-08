/**
 * Backup Manager — creates timestamped backups before any config modification.
 *
 * Rules:
 *   - Only backs up files in the ALLOWED_BACKUP set (config files, not source)
 *   - Backups are stored in .backups/{YYYY-MM-DD_HH-MM-SS}/
 *   - Never touches src/, app/, or any .ts/.tsx/.py source files
 *   - restore(id) reverts a specific backup
 *   - list() shows all available backups
 */
"use strict";

const fs   = require("fs");
const path = require("path");

const ROOT        = path.resolve(__dirname, "..");
const BACKUP_ROOT = path.join(ROOT, ".backups");

// Only these relative paths (from ROOT) may be backed up / modified
const ALLOWED_BACKUP = new Set([
  "package.json",
  "package-lock.json",
  ".npmrc",
  ".nvmrc",
  ".node-version",
  "vite.config.ts",
  "vite.config.js",
  "tsconfig.json",
  "tsconfig.node.json",
  ".env",
  ".env.local",
  ".env.development",
  "eslint.config.js",
  "eslint.config.mjs",
]);

// Patterns that are absolutely never modifiable (belt + suspenders)
const PROTECTED_PATTERNS = [
  /^src\//,
  /^app\//,
  /^migrations\//,
  /^\.github\//,
  /\.py$/,
  /\.ts$/,
  /\.tsx$/,
  /Dockerfile/,
  /render\.yaml/,
];

function isProtected(relPath) {
  const norm = relPath.replace(/\\/g, "/");
  return PROTECTED_PATTERNS.some(p => p.test(norm));
}

function isAllowed(relPath) {
  const norm = relPath.replace(/\\/g, "/");
  return ALLOWED_BACKUP.has(norm) && !isProtected(norm);
}

function timestamp() {
  return new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
}

/**
 * Create a backup of one or more files.
 * @param {string[]} relPaths — paths relative to project root
 * @param {string} [reason]  — human-readable reason (stored in manifest)
 * @returns {{ id: string, dir: string, files: string[] }}
 */
function create(relPaths, reason = "unspecified") {
  const ts  = timestamp();
  const dir = path.join(BACKUP_ROOT, ts);
  fs.mkdirSync(dir, { recursive: true });

  const backed = [];
  const skipped = [];

  for (const rel of relPaths) {
    if (!isAllowed(rel)) {
      skipped.push({ path: rel, reason: isProtected(rel) ? "protected" : "not-in-allowlist" });
      continue;
    }
    const src = path.join(ROOT, rel);
    if (!fs.existsSync(src)) {
      skipped.push({ path: rel, reason: "not-found" });
      continue;
    }
    const dest = path.join(dir, rel.replace(/\//g, "__"));
    fs.copyFileSync(src, dest);
    backed.push(rel);
  }

  // Write manifest
  const manifest = { id: ts, reason, created: new Date().toISOString(), files: backed, skipped };
  fs.writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(manifest, null, 2));

  return { id: ts, dir, files: backed, skipped };
}

/**
 * Restore all files from a backup by ID (the timestamp string).
 * @param {string} id
 */
function restore(id) {
  const dir = path.join(BACKUP_ROOT, id);
  if (!fs.existsSync(dir)) throw new Error(`Backup not found: ${id}`);

  const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
  const restored = [];

  for (const rel of manifest.files) {
    const src  = path.join(dir, rel.replace(/\//g, "__"));
    const dest = path.join(ROOT, rel);
    if (!fs.existsSync(src)) continue;
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
    restored.push(rel);
  }

  return { id, restored };
}

/**
 * List all available backups (newest first).
 */
function list() {
  if (!fs.existsSync(BACKUP_ROOT)) return [];
  return fs.readdirSync(BACKUP_ROOT)
    .filter(d => fs.existsSync(path.join(BACKUP_ROOT, d, "manifest.json")))
    .sort()
    .reverse()
    .map(d => {
      const m = JSON.parse(fs.readFileSync(path.join(BACKUP_ROOT, d, "manifest.json"), "utf8"));
      return m;
    });
}

/**
 * Prune backups older than `days` days (default 30).
 */
function prune(days = 30) {
  if (!fs.existsSync(BACKUP_ROOT)) return 0;
  const cutoff = Date.now() - days * 86400 * 1000;
  let count = 0;
  for (const d of fs.readdirSync(BACKUP_ROOT)) {
    const mf = path.join(BACKUP_ROOT, d, "manifest.json");
    if (!fs.existsSync(mf)) continue;
    const m = JSON.parse(fs.readFileSync(mf, "utf8"));
    if (new Date(m.created).getTime() < cutoff) {
      fs.rmSync(path.join(BACKUP_ROOT, d), { recursive: true, force: true });
      count++;
    }
  }
  return count;
}

module.exports = { create, restore, list, prune, isAllowed, isProtected, ALLOWED_BACKUP };
