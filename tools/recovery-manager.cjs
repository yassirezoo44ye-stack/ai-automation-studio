/**
 * Recovery Manager — orchestrates multi-step build recovery sequences.
 *
 * Coordinates: env-checker → health-check → repair-engine → verify.
 * Stages gate on each other: a failed stage stops the sequence unless
 * the failure is classified as recoverable by the repair engine.
 *
 * Never edits source files. Backup is created automatically by repair-engine
 * when any config file is touched.
 */
"use strict";

const health     = require("./health-check.cjs");
const repair     = require("./repair-engine.cjs");
const log        = require("./logger.cjs");
const backup     = require("./backup-manager.cjs");
const bus        = require("./event-bus.cjs");
const telemetry  = require("./telemetry.cjs");
const tracer     = require("./tracer.cjs");
const guard      = require("./concurrency-guard.cjs");

// ── Stage definitions ──────────────────────────────────────────────────────────

const STAGES = ["env-check", "dependency-install", "health-verify", "done"];

// ── Pipeline ───────────────────────────────────────────────────────────────────

/**
 * Run the full recovery pipeline.
 *
 * @param {{ silent?: boolean, maxAttempts?: number }} opts
 * @returns {Promise<RecoveryResult>}
 */
async function _runPipelineCore(opts = {}) {
  const { silent = false, maxAttempts = 2 } = opts;
  const stages  = [];
  const started = Date.now();

  function stageLog(name, status, detail) {
    const entry = { stage: name, status, detail, ts: new Date().toISOString() };
    stages.push(entry);
    if (!silent) {
      const icon = status === "pass" ? "✅" : status === "warn" ? "⚠️" : status === "skip" ? "⏭️" : "❌";
      process.stdout.write(`  ${icon} ${name}: ${detail}\n`);
    }
    log.runtime[status === "fail" ? "error" : "info"](`[Recovery] ${name}: ${status}`, { detail });
  }

  // ── Stage 1: Environment snapshot ────────────────────────────────────────────
  let envReport;
  try {
    const envChecker = require("./env-checker.cjs");
    envReport = await envChecker.snapshot();
    const nodeOk = envReport.node.ok;
    const pmOk   = !!envReport.packageManager.version;
    stageLog("env-check", nodeOk && pmOk ? "pass" : "warn",
      `Node ${envReport.node.version}, PM: ${envReport.packageManager.pm} ${envReport.packageManager.version || "??"}`);
  } catch (err) {
    stageLog("env-check", "fail", err.message);
    return buildResult(false, stages, started);
  }

  // ── Stage 2: Dependency install (self-healing) ────────────────────────────────
  const nodeModules = require("path").join(__dirname, "..", "node_modules");
  const needInstall = !require("fs").existsSync(nodeModules);
  let installAttempt = 0;
  let installOk = !needInstall;

  if (needInstall) {
    while (installAttempt < maxAttempts && !installOk) {
      installAttempt++;
      stageLog("dependency-install", "warn", `Attempt ${installAttempt}/${maxAttempts}`);
      const res = repair.installDependencies();
      installOk = res.ok;
      if (!res.ok) {
        // Classify and log
        const fc = repair.FAILURE.INSTALL_FAILED;
        if (repair.RepairEngine.tooManyAttempts(fc)) break;
      }
    }
    stageLog("dependency-install",
      installOk ? "pass" : "fail",
      installOk ? "dependencies installed" : "all install strategies failed — check npm logs");
  } else {
    stageLog("dependency-install", "skip", "node_modules already present");
  }

  if (!installOk) {
    return buildResult(false, stages, started);
  }

  // ── Stage 3: Health verify ────────────────────────────────────────────────────
  let healthReport;
  try {
    healthReport = await health.run();
    stageLog("health-verify",
      healthReport.healthy ? "pass" : healthReport.fails === 0 ? "warn" : "fail",
      `score ${healthReport.score}/100, ${healthReport.fails} failures, ${healthReport.warns} warnings`);
  } catch (err) {
    stageLog("health-verify", "fail", err.message);
    return buildResult(false, stages, started);
  }

  stageLog("done", "pass", `Recovery complete in ${Date.now() - started}ms`);
  return buildResult(healthReport.healthy, stages, started, healthReport);
}

/**
 * Run the full recovery pipeline with event bus, telemetry, tracing, and
 * concurrency guard layered on top of the core pipeline.
 *
 * @param {{ silent?: boolean, maxAttempts?: number }} opts
 * @returns {Promise<RecoveryResult>}
 */
async function runPipeline(opts = {}) {
  const lock = guard.acquire("recovery");
  if (!lock.acquired) {
    const msg = `Recovery already running: ${lock.reason}`;
    log.runtime.warn(msg);
    return { ok: false, stages: [], durationMs: 0, healthReport: null, ts: new Date().toISOString(), skipped: true, reason: msg };
  }

  const span = tracer.startSpan(tracer.PHASES.VERIFICATION);
  bus.emit(bus.EVENTS.RECOVERY_STARTED, { ts: new Date().toISOString() });

  let result;
  try {
    result = await _runPipelineCore(opts);
  } catch (err) {
    result = { ok: false, stages: [], durationMs: 0, healthReport: null, ts: new Date().toISOString(), error: err.message };
  } finally {
    lock.release();
    span.finish(result && !result.ok ? "pipeline failed" : undefined);
  }

  const dur    = result.durationMs || 0;
  const score  = result.healthReport ? result.healthReport.score : -1;

  telemetry.recordBuild({ durationMs: dur, success: result.ok, outcome: result.ok ? "recovery-passed" : "recovery-failed" });
  if (score >= 0) telemetry.recordDoctor({ durationMs: dur, healthScore: score, healthy: result.ok });

  bus.emit(result.ok ? bus.EVENTS.RECOVERY_COMPLETED : bus.EVENTS.RECOVERY_FAILED, {
    durationMs: dur, healthScore: score, stageCount: (result.stages || []).length,
  });

  return result;
}

function buildResult(ok, stages, started, healthReport = null) {
  return {
    ok,
    stages,
    durationMs    : Date.now() - started,
    healthReport,
    ts            : new Date().toISOString(),
  };
}

// ── On-demand recovery for a specific failure ──────────────────────────────────

/**
 * Recover from a single classified failure.
 * Used by the dev server wrapper when a subprocess crashes.
 *
 * @param {{ stderr?: string, stdout?: string, context?: string }} failure
 */
async function recoverFailure(failure) {
  const span = tracer.startSpan(tracer.PHASES.REPAIR, { service: "repair-engine" });
  bus.emit(bus.EVENTS.REPAIR_STARTED, { failure });
  const t0 = Date.now();
  let result;
  try {
    result = await repair.RepairEngine.recover(failure);
  } catch (err) {
    result = { ok: false, error: err.message };
  }
  const dur = Date.now() - t0;
  span.finish(!result.ok ? "repair failed" : undefined);
  telemetry.recordRepair({ durationMs: dur, success: result.ok, rootCause: failure.stderr ? repair.classify(failure.stderr, failure.stdout || "") : undefined, outcome: result.ok ? "repaired" : "unrecoverable" });
  bus.emit(result.ok ? bus.EVENTS.REPAIR_COMPLETED : bus.EVENTS.REPAIR_FAILED, { durationMs: dur, result });
  return result;
}

// ── Backup helpers ─────────────────────────────────────────────────────────────

function listBackups() { return backup.list(); }
function restoreBackup(id) { return backup.restore(id); }
function pruneBackups(days = 30) { return backup.prune(days); }

module.exports = { runPipeline, recoverFailure, listBackups, restoreBackup, pruneBackups };
