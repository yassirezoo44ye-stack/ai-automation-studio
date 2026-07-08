"use strict";
/**
 * Lightweight OpenTelemetry-compatible span-based tracer.
 * No external deps. Spans are stored in a ring buffer and persisted
 * to logs/traces.jsonl.
 *
 * Build phases tracked:
 *   EnvironmentCheck, Install, Repair, Verification, Launch, Rollback
 *
 * @module tracer
 */
const fs   = require("fs");
const path = require("path");
const { randomBytes } = require("crypto");

// ── ID generation ─────────────────────────────────────────────────────────────

function _traceId()  { return randomBytes(16).toString("hex"); }
function _spanId()   { return randomBytes(8).toString("hex"); }

// ── Persistence ───────────────────────────────────────────────────────────────

const LOG_DIR    = path.resolve(__dirname, "..", "logs");
const TRACE_FILE = path.join(LOG_DIR, "traces.jsonl");

function _persist(span) {
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    fs.appendFileSync(TRACE_FILE, JSON.stringify(span) + "\n", "utf8");
  } catch (_) { /* non-fatal */ }
}

// ── Ring buffer ───────────────────────────────────────────────────────────────

const BUFFER_MAX = 2000;
const _finished  = [];
const _active    = new Map();

// ── Span ──────────────────────────────────────────────────────────────────────

/**
 * @typedef {Object} SpanData
 * @property {string}   traceId
 * @property {string}   spanId
 * @property {string}   [parentId]
 * @property {string}   name
 * @property {string}   service
 * @property {number}   startedAt   Unix ms
 * @property {number}   [endedAt]   Unix ms (set on finish)
 * @property {number}   [durationMs]
 * @property {Object}   tags
 * @property {Array}    events
 * @property {string}   [error]
 * @property {string}   status      "active"|"ok"|"error"
 */

class Span {
  /**
   * @param {string} name
   * @param {string} service
   * @param {string} traceId
   * @param {string} [parentId]
   */
  constructor(name, service, traceId, parentId) {
    this.traceId   = traceId  || _traceId();
    this.spanId    = _spanId();
    this.parentId  = parentId || null;
    this.name      = name;
    this.service   = service  || "build-system";
    this.startedAt = Date.now();
    this.endedAt   = null;
    this.durationMs = null;
    this.tags      = {};
    this.events    = [];
    this.error     = null;
    this.status    = "active";
    _active.set(this.spanId, this);
  }

  /**
   * Attach a key/value tag.
   * @param {string} key
   * @param {*}      value
   * @returns {Span}
   */
  setTag(key, value) {
    this.tags[key] = value;
    return this;
  }

  /**
   * Add a timed event within this span.
   * @param {string} name
   * @param {Object} [attrs]
   * @returns {Span}
   */
  addEvent(name, attrs) {
    this.events.push({ name, ts: Date.now(), ...attrs });
    return this;
  }

  /**
   * Finish the span.
   * @param {string|Error} [error]  If provided, marks span as error
   * @returns {SpanData}
   */
  finish(error) {
    if (this.status !== "active") return this._toJSON();
    this.endedAt    = Date.now();
    this.durationMs = this.endedAt - this.startedAt;
    _active.delete(this.spanId);

    if (error) {
      this.error  = error instanceof Error ? error.message : String(error);
      this.status = "error";
    } else {
      this.status = "ok";
    }

    const data = this._toJSON();
    _finished.push(data);
    if (_finished.length > BUFFER_MAX) _finished.shift();
    _persist(data);
    return data;
  }

  /** @returns {SpanData} */
  _toJSON() {
    return {
      traceId   : this.traceId,
      spanId    : this.spanId,
      parentId  : this.parentId,
      name      : this.name,
      service   : this.service,
      startedAt : this.startedAt,
      endedAt   : this.endedAt,
      durationMs: this.durationMs,
      tags      : { ...this.tags },
      events    : [...this.events],
      error     : this.error,
      status    : this.status,
    };
  }

  // ── Context manager ───────────────────────────────────────────────────────

  /** Alias for use in Promise chains: `await span.wrap(asyncFn)` */
  async wrap(fn) {
    try {
      const result = await fn(this);
      this.finish();
      return result;
    } catch (err) {
      this.finish(err);
      throw err;
    }
  }
}

// ── Tracer API ────────────────────────────────────────────────────────────────

/**
 * Start a new span.
 *
 * @param {string} name           Phase name (e.g. "EnvironmentCheck")
 * @param {Object} [opts]
 * @param {string} [opts.service] Service label
 * @param {string} [opts.traceId] Existing trace ID to join
 * @param {string} [opts.parentId] Parent span ID
 * @returns {Span}
 */
function startSpan(name, opts) {
  opts = opts || {};
  return new Span(name, opts.service, opts.traceId, opts.parentId);
}

/**
 * Recent finished spans (newest last).
 *
 * @param {number} [n=100]
 * @returns {SpanData[]}
 */
function recent(n) {
  return _finished.slice(-(n || 100));
}

/**
 * Currently active (unfinished) spans.
 *
 * @returns {SpanData[]}
 */
function active() {
  return [..._active.values()].map(s => s._toJSON());
}

/**
 * All spans for a given trace ID.
 *
 * @param {string} traceId
 * @returns {SpanData[]}
 */
function getTrace(traceId) {
  const finished = _finished.filter(s => s.traceId === traceId);
  const inFlight = [..._active.values()]
    .filter(s => s.traceId === traceId)
    .map(s => s._toJSON());
  return [...finished, ...inFlight].sort((a, b) => a.startedAt - b.startedAt);
}

/**
 * Helper: run an async function wrapped in a span.
 * The span is automatically finished (success or error).
 *
 * @param {string}   name
 * @param {Function} fn    async (span) => result
 * @param {Object}   [opts]
 * @returns {Promise<*>}
 */
async function withSpan(name, fn, opts) {
  const span = startSpan(name, opts);
  try {
    const result = await fn(span);
    span.finish();
    return result;
  } catch (err) {
    span.finish(err);
    throw err;
  }
}

/**
 * Known build-phase span names.
 * @enum {string}
 */
const PHASES = {
  ENVIRONMENT_CHECK : "EnvironmentCheck",
  INSTALL           : "Install",
  REPAIR            : "Repair",
  VERIFICATION      : "Verification",
  LAUNCH            : "Launch",
  ROLLBACK          : "Rollback",
};

module.exports = { startSpan, recent, active, getTrace, withSpan, PHASES };
