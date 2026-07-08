"use strict";
/**
 * Concurrency guard: prevents multiple simultaneous repair/install/rollback
 * operations using a combination of file-based lock and in-process mutex.
 *
 * File lock survives process boundaries (prevents two terminal sessions).
 * In-process mutex prevents re-entrant calls within the same process.
 *
 * @module concurrency-guard
 */
const fs   = require("fs");
const path = require("path");

// ── Configuration ─────────────────────────────────────────────────────────────

const LOCK_DIR     = path.resolve(__dirname, "..", ".locks");
const LOCK_TTL_MS  = 10 * 60 * 1000; // 10 minutes: stale lock threshold

// ── In-process mutex (Map of operation → boolean) ───────────────────────────

const _inProcess = new Map();

// ── File lock helpers ─────────────────────────────────────────────────────────

function _lockPath(op) {
  fs.mkdirSync(LOCK_DIR, { recursive: true });
  return path.join(LOCK_DIR, `${op}.lock`);
}

/**
 * @typedef {Object} LockInfo
 * @property {number} pid
 * @property {string} op
 * @property {number} ts  Unix ms when lock was acquired
 */

function _readLock(lockPath) {
  try {
    return JSON.parse(fs.readFileSync(lockPath, "utf8"));
  } catch (_) { return null; }
}

function _writeLock(lockPath, op) {
  fs.writeFileSync(lockPath, JSON.stringify({ pid: process.pid, op, ts: Date.now() }), "utf8");
}

function _removeLock(lockPath) {
  try { fs.unlinkSync(lockPath); } catch (_) {}
}

function _isStale(info) {
  return !info || (Date.now() - info.ts) > LOCK_TTL_MS;
}

// ── Core API ──────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} AcquireResult
 * @property {boolean} acquired   True if lock was acquired
 * @property {string}  op         Operation name
 * @property {string}  [reason]   Why acquisition failed
 * @property {LockInfo} [holder]  Who holds the lock (if not acquired)
 * @property {Function} release   Call when the operation is done
 */

/**
 * Try to acquire a named lock.
 *
 * @param {string} op  Operation name: "repair"|"install"|"rollback"|"doctor"
 * @returns {AcquireResult}
 */
function acquire(op) {
  const lockPath = _lockPath(op);

  // In-process check first (fastest)
  if (_inProcess.get(op)) {
    return {
      acquired: false,
      op,
      reason : "already running in this process",
      release: () => {},
    };
  }

  // File lock check
  const existing = _readLock(lockPath);
  if (existing && !_isStale(existing)) {
    return {
      acquired: false,
      op,
      reason : `locked by PID ${existing.pid} since ${new Date(existing.ts).toISOString()}`,
      holder : existing,
      release: () => {},
    };
  }

  // Stale or absent — acquire
  _writeLock(lockPath, op);
  _inProcess.set(op, true);

  let released = false;
  function release() {
    if (released) return;
    released = true;
    _inProcess.delete(op);
    _removeLock(lockPath);
  }

  return { acquired: true, op, release };
}

/**
 * Run an async function with exclusive lock on `op`.
 * Throws if the lock cannot be acquired.
 *
 * @param {string}   op
 * @param {Function} fn  async () => result
 * @returns {Promise<*>}
 */
async function withLock(op, fn) {
  const lock = acquire(op);
  if (!lock.acquired) {
    throw new Error(`Cannot acquire lock for "${op}": ${lock.reason}`);
  }
  try {
    return await fn();
  } finally {
    lock.release();
  }
}

/**
 * List all currently held file locks and their info.
 *
 * @returns {Array<{op: string, info: LockInfo, stale: boolean}>}
 */
function listLocks() {
  try {
    fs.mkdirSync(LOCK_DIR, { recursive: true });
    return fs.readdirSync(LOCK_DIR)
      .filter(f => f.endsWith(".lock"))
      .map(f => {
        const lockPath = path.join(LOCK_DIR, f);
        const info     = _readLock(lockPath);
        return { op: f.replace(".lock", ""), info, stale: _isStale(info) };
      });
  } catch (_) { return []; }
}

/**
 * Force-remove a lock (emergency use only).
 *
 * @param {string} op
 * @returns {boolean} true if a lock was removed
 */
function forceClear(op) {
  const lockPath = _lockPath(op);
  const existed  = fs.existsSync(lockPath);
  _removeLock(lockPath);
  _inProcess.delete(op);
  return existed;
}

/**
 * Check whether a specific operation is currently locked.
 *
 * @param {string} op
 * @returns {boolean}
 */
function isLocked(op) {
  if (_inProcess.get(op)) return true;
  const existing = _readLock(_lockPath(op));
  return !!(existing && !_isStale(existing));
}

module.exports = { acquire, withLock, listLocks, forceClear, isLocked };
