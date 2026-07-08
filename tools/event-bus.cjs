"use strict";
/**
 * Structured event bus for the Self-Healing Build System.
 * Wraps Node's EventEmitter with typed events, history ring buffer,
 * and optional persistence to logs/events.jsonl.
 *
 * @module event-bus
 */
const { EventEmitter } = require("events");
const fs   = require("fs");
const path = require("path");

// ── Event type constants ────────────────────────────────────────────────────

/** @enum {string} */
const EVENTS = {
  BUILD_STARTED        : "BuildStarted",
  BUILD_COMPLETED      : "BuildCompleted",
  BUILD_FAILED         : "BuildFailed",
  REPAIR_STARTED       : "RepairStarted",
  REPAIR_COMPLETED     : "RepairCompleted",
  REPAIR_FAILED        : "RepairFailed",
  RECOVERY_STARTED     : "RecoveryStarted",
  RECOVERY_COMPLETED   : "RecoveryCompleted",
  RECOVERY_FAILED      : "RecoveryFailed",
  DOCTOR_STARTED       : "DoctorStarted",
  DOCTOR_COMPLETED     : "DoctorCompleted",
  ROLLBACK_STARTED     : "RollbackStarted",
  ROLLBACK_COMPLETED   : "RollbackCompleted",
  ROLLBACK_FAILED      : "RollbackFailed",
  INSTALL_STARTED      : "InstallStarted",
  INSTALL_COMPLETED    : "InstallCompleted",
  INSTALL_FAILED_EVENT : "InstallFailed",
};

// ── Ring buffer ─────────────────────────────────────────────────────────────

const HISTORY_MAX = 500;
const _history    = [];

/**
 * @typedef {Object} BusEvent
 * @property {string}  type      - EVENTS.* constant value
 * @property {string}  ts        - ISO timestamp
 * @property {Object}  [payload] - event-specific data
 */

function _record(type, payload) {
  /** @type {BusEvent} */
  const ev = { type, ts: new Date().toISOString(), payload: payload || {} };
  _history.push(ev);
  if (_history.length > HISTORY_MAX) _history.shift();
  _persistEvent(ev);
  return ev;
}

// ── Persistence (best-effort, never throws) ─────────────────────────────────

const LOG_DIR    = path.resolve(__dirname, "..", "logs");
const EVENTS_LOG = path.join(LOG_DIR, "events.jsonl");

function _persistEvent(ev) {
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    fs.appendFileSync(EVENTS_LOG, JSON.stringify(ev) + "\n", "utf8");
  } catch (_) { /* non-fatal */ }
}

// ── Core emitter ─────────────────────────────────────────────────────────────

const _emitter = new EventEmitter();
_emitter.setMaxListeners(50);

/**
 * Publish a typed event to all subscribers.
 *
 * @param {string} type    - One of the EVENTS.* values
 * @param {Object} payload - Arbitrary event data
 * @returns {BusEvent}     The recorded event object
 */
function emit(type, payload) {
  const ev = _record(type, payload);
  _emitter.emit(type, ev);
  _emitter.emit("*", ev);  // wildcard channel
  return ev;
}

/**
 * Subscribe to a specific event type.
 *
 * @param {string}   type     - Event type or "*" for all events
 * @param {Function} handler  - Called with (BusEvent)
 * @returns {Function}        Unsubscribe function
 */
function on(type, handler) {
  _emitter.on(type, handler);
  return () => _emitter.off(type, handler);
}

/**
 * Subscribe to an event type exactly once.
 *
 * @param {string}   type
 * @param {Function} handler
 */
function once(type, handler) {
  _emitter.once(type, handler);
}

/**
 * Unsubscribe a handler.
 *
 * @param {string}   type
 * @param {Function} handler
 */
function off(type, handler) {
  _emitter.off(type, handler);
}

/**
 * Return recent event history.
 *
 * @param {number} [n=100]   How many events (newest last)
 * @param {string} [type]    Filter by event type
 * @returns {BusEvent[]}
 */
function history(n, type) {
  n = n || 100;
  let evs = type ? _history.filter(e => e.type === type) : _history;
  return evs.slice(-n);
}

/**
 * Clear history (useful in tests).
 */
function clearHistory() {
  _history.length = 0;
}

module.exports = { emit, on, once, off, history, clearHistory, EVENTS };
