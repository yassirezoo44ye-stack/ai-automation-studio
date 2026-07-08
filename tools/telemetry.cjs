"use strict";
/**
 * Recovery telemetry: records build/repair/recovery operations with duration,
 * success rate, retry counts, strategies, root causes, and final outcomes.
 * Also exposes Prometheus-format metrics.
 *
 * @module telemetry
 */
const fs   = require("fs");
const path = require("path");
const http = require("http");

// ── Storage ─────────────────────────────────────────────────────────────────

const LOG_DIR  = path.resolve(__dirname, "..", "logs");
const TEL_FILE = path.join(LOG_DIR, "telemetry.jsonl");

function _persist(record) {
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    fs.appendFileSync(TEL_FILE, JSON.stringify(record) + "\n", "utf8");
  } catch (_) { /* non-fatal */ }
}

// ── In-process counters (reset on restart) ───────────────────────────────────

const _counters = {
  build_total        : 0,
  build_success      : 0,
  build_failed       : 0,
  repair_attempts    : 0,
  repair_success     : 0,
  repair_failed      : 0,
  doctor_runs        : 0,
  install_attempts   : 0,
  install_success    : 0,
  install_failed     : 0,
  rollback_total     : 0,
  rollback_success   : 0,
};

/** @type {number[]} */
const _buildDurations   = [];
/** @type {number[]} */
const _installDurations = [];
/** @type {number} last health score 0–100 */
let _lastHealthScore    = -1;

const MAX_SAMPLES = 1000;
function _pushSample(arr, val) {
  arr.push(val);
  if (arr.length > MAX_SAMPLES) arr.shift();
}

// ── Telemetry record types ───────────────────────────────────────────────────

/**
 * @typedef {Object} TelemetryRecord
 * @property {string}  kind          - "build"|"repair"|"install"|"doctor"|"rollback"
 * @property {string}  ts            - ISO timestamp
 * @property {number}  durationMs    - Wall-clock milliseconds
 * @property {boolean} success       - Whether the operation succeeded
 * @property {number}  [retryCount]  - Number of retries attempted
 * @property {string}  [strategy]    - Strategy/method used
 * @property {string}  [rootCause]   - FAILURE.* constant or free text
 * @property {string}  [outcome]     - Final human-readable outcome
 * @property {Object}  [extra]       - Kind-specific extra data
 */

/**
 * Record a completed build operation.
 *
 * @param {Object} opts
 * @param {number}  opts.durationMs
 * @param {boolean} opts.success
 * @param {string}  [opts.outcome]
 * @param {Object}  [opts.extra]
 * @returns {TelemetryRecord}
 */
function recordBuild({ durationMs, success, outcome, extra }) {
  _counters.build_total++;
  if (success) _counters.build_success++; else _counters.build_failed++;
  _pushSample(_buildDurations, durationMs);
  const rec = { kind: "build", ts: new Date().toISOString(), durationMs, success, outcome, extra };
  _persist(rec);
  return rec;
}

/**
 * Record a repair attempt.
 *
 * @param {Object} opts
 * @param {number}  opts.durationMs
 * @param {boolean} opts.success
 * @param {number}  [opts.retryCount]
 * @param {string}  [opts.strategy]
 * @param {string}  [opts.rootCause]
 * @param {string}  [opts.outcome]
 * @param {Object}  [opts.extra]
 * @returns {TelemetryRecord}
 */
function recordRepair({ durationMs, success, retryCount, strategy, rootCause, outcome, extra }) {
  _counters.repair_attempts++;
  if (success) _counters.repair_success++; else _counters.repair_failed++;
  const rec = {
    kind: "repair", ts: new Date().toISOString(), durationMs, success,
    retryCount: retryCount || 0, strategy, rootCause, outcome, extra,
  };
  _persist(rec);
  return rec;
}

/**
 * Record a dependency install attempt.
 *
 * @param {Object} opts
 * @param {number}  opts.durationMs
 * @param {boolean} opts.success
 * @param {number}  [opts.attempts]
 * @param {string}  [opts.strategy]  Which pm/strategy worked
 * @param {string}  [opts.outcome]
 * @returns {TelemetryRecord}
 */
function recordInstall({ durationMs, success, attempts, strategy, outcome }) {
  _counters.install_attempts++;
  if (success) _counters.install_success++; else _counters.install_failed++;
  _pushSample(_installDurations, durationMs);
  const rec = {
    kind: "install", ts: new Date().toISOString(), durationMs, success,
    retryCount: (attempts || 1) - 1, strategy, outcome,
  };
  _persist(rec);
  return rec;
}

/**
 * Record a doctor run.
 *
 * @param {Object} opts
 * @param {number}  opts.durationMs
 * @param {number}  opts.healthScore  0–100
 * @param {boolean} opts.healthy
 * @param {Object}  [opts.extra]
 * @returns {TelemetryRecord}
 */
function recordDoctor({ durationMs, healthScore, healthy, extra }) {
  _counters.doctor_runs++;
  _lastHealthScore = healthScore;
  const rec = {
    kind: "doctor", ts: new Date().toISOString(), durationMs,
    success: healthy, outcome: `health=${healthScore}`, extra,
  };
  _persist(rec);
  return rec;
}

/**
 * Record a rollback operation.
 *
 * @param {Object} opts
 * @param {number}  opts.durationMs
 * @param {boolean} opts.success
 * @param {string}  [opts.backupId]
 * @param {string}  [opts.outcome]
 * @returns {TelemetryRecord}
 */
function recordRollback({ durationMs, success, backupId, outcome }) {
  _counters.rollback_total++;
  if (success) _counters.rollback_success++;
  const rec = {
    kind: "rollback", ts: new Date().toISOString(), durationMs, success,
    outcome, extra: { backupId },
  };
  _persist(rec);
  return rec;
}

// ── Aggregates ───────────────────────────────────────────────────────────────

function _avg(arr) {
  if (!arr.length) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

/**
 * Return current metrics snapshot.
 *
 * @returns {Object}
 */
function snapshot() {
  const repairSuccessRate = _counters.repair_attempts
    ? _counters.repair_success / _counters.repair_attempts : 0;
  return {
    counters: { ..._counters },
    rates: {
      repair_success_rate  : +repairSuccessRate.toFixed(4),
      install_success_rate : _counters.install_attempts
        ? +(_counters.install_success / _counters.install_attempts).toFixed(4) : 0,
      build_success_rate   : _counters.build_total
        ? +(_counters.build_success / _counters.build_total).toFixed(4) : 0,
    },
    averages: {
      build_duration_ms   : +_avg(_buildDurations).toFixed(2),
      install_duration_ms : +_avg(_installDurations).toFixed(2),
    },
    last_health_score: _lastHealthScore,
    ts: new Date().toISOString(),
  };
}

// ── Prometheus text format ───────────────────────────────────────────────────

/**
 * Return metrics in Prometheus text exposition format.
 *
 * Metrics exported:
 *   build_duration_seconds         - Average build duration
 *   repair_attempts_total          - Total repair attempts
 *   repair_success_total           - Successful repairs
 *   repair_failures_total          - Failed repairs
 *   environment_health_score       - Last health-check score (0–100)
 *   dependency_install_duration    - Average install duration (seconds)
 *   doctor_runs_total              - Total doctor runs
 *
 * @returns {string}
 */
function prometheusText() {
  const snap = snapshot();
  const c    = snap.counters;
  const avg  = snap.averages;
  const lines = [
    "# HELP build_duration_seconds Average build duration in seconds",
    "# TYPE build_duration_seconds gauge",
    `build_duration_seconds ${(avg.build_duration_ms / 1000).toFixed(6)}`,

    "# HELP repair_attempts_total Total number of repair attempts",
    "# TYPE repair_attempts_total counter",
    `repair_attempts_total ${c.repair_attempts}`,

    "# HELP repair_success_total Total successful repairs",
    "# TYPE repair_success_total counter",
    `repair_success_total ${c.repair_success}`,

    "# HELP repair_failures_total Total failed repairs",
    "# TYPE repair_failures_total counter",
    `repair_failures_total ${c.repair_failed}`,

    "# HELP environment_health_score Last environment health score (0-100)",
    "# TYPE environment_health_score gauge",
    `environment_health_score ${snap.last_health_score < 0 ? 0 : snap.last_health_score}`,

    "# HELP dependency_install_duration Average dependency install duration in seconds",
    "# TYPE dependency_install_duration gauge",
    `dependency_install_duration ${(avg.install_duration_ms / 1000).toFixed(6)}`,

    "# HELP doctor_runs_total Total number of doctor diagnostic runs",
    "# TYPE doctor_runs_total counter",
    `doctor_runs_total ${c.doctor_runs}`,

    "# HELP build_total_total Total build attempts",
    "# TYPE build_total_total counter",
    `build_total_total ${c.build_total}`,

    "# HELP build_success_total Successful build attempts",
    "# TYPE build_success_total counter",
    `build_success_total ${c.build_success}`,
  ];
  return lines.join("\n") + "\n";
}

// ── HTTP metrics endpoint ────────────────────────────────────────────────────

let _server = null;

/**
 * Start an HTTP server exposing /metrics (Prometheus) and /metrics/json.
 * Idempotent — safe to call multiple times.
 *
 * @param {number} [port=9091]
 * @returns {Promise<http.Server>}
 */
function startMetricsServer(port) {
  port = port || 9091;
  if (_server) return Promise.resolve(_server);

  _server = http.createServer((req, res) => {
    if (req.method !== "GET") {
      res.writeHead(405).end("Method Not Allowed");
      return;
    }
    if (req.url === "/metrics") {
      res.writeHead(200, { "Content-Type": "text/plain; version=0.0.4; charset=utf-8" });
      res.end(prometheusText());
    } else if (req.url === "/metrics/json" || req.url === "/") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(snapshot(), null, 2));
    } else {
      res.writeHead(404).end("Not Found");
    }
  });

  return new Promise((resolve, reject) => {
    _server.listen(port, "127.0.0.1", () => resolve(_server));
    _server.on("error", reject);
  });
}

/**
 * Stop the metrics server.
 *
 * @returns {Promise<void>}
 */
function stopMetricsServer() {
  if (!_server) return Promise.resolve();
  return new Promise((resolve) => _server.close(resolve));
}

module.exports = {
  recordBuild,
  recordRepair,
  recordInstall,
  recordDoctor,
  recordRollback,
  snapshot,
  prometheusText,
  startMetricsServer,
  stopMetricsServer,
};
