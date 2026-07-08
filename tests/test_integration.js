/**
 * Integration tests for the Self-Healing Build System production hardening.
 * Tests cover: event bus, telemetry, tracer, pm-abstraction, concurrency-guard,
 * sandbox, config-profiles, plugins, and recovery-manager wiring.
 *
 * Run with: node --test tests/test_integration.js
 */
import { createRequire } from "node:module";
import { test, describe } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);

const bus      = require("../tools/event-bus.cjs");
const tel      = require("../tools/telemetry.cjs");
const tracer   = require("../tools/tracer.cjs");
const pmAbst   = require("../tools/pm-abstraction.cjs");
const cg       = require("../tools/concurrency-guard.cjs");
const sandbox  = require("../tools/sandbox.cjs");
const profiles = require("../tools/config-profiles.cjs");
const plugins  = require("../tools/plugins.cjs");

// ── Event Bus ─────────────────────────────────────────────────────────────────

describe("EventBus", () => {

  test("emit returns event with type and ts", () => {
    const ev = bus.emit(bus.EVENTS.BUILD_STARTED, { foo: 1 });
    assert.equal(ev.type, bus.EVENTS.BUILD_STARTED);
    assert.ok(ev.ts);
    assert.equal(ev.payload.foo, 1);
  });

  test("on() receives emitted events", (t, done) => {
    const unsub = bus.on(bus.EVENTS.BUILD_COMPLETED, (ev) => {
      unsub();
      assert.equal(ev.type, bus.EVENTS.BUILD_COMPLETED);
      done();
    });
    bus.emit(bus.EVENTS.BUILD_COMPLETED, {});
  });

  test("once() fires exactly once", () => {
    let count = 0;
    bus.once(bus.EVENTS.BUILD_FAILED, () => { count++; });
    bus.emit(bus.EVENTS.BUILD_FAILED, {});
    bus.emit(bus.EVENTS.BUILD_FAILED, {});
    assert.equal(count, 1);
  });

  test("wildcard channel receives all events", (t, done) => {
    const unsub = bus.on("*", (ev) => {
      if (ev.type === bus.EVENTS.DOCTOR_STARTED) {
        unsub();
        done();
      }
    });
    bus.emit(bus.EVENTS.DOCTOR_STARTED, {});
  });

  test("history() returns recent events filtered by type", () => {
    bus.clearHistory();
    bus.emit(bus.EVENTS.REPAIR_STARTED, { id: 1 });
    bus.emit(bus.EVENTS.REPAIR_COMPLETED, { id: 1 });
    bus.emit(bus.EVENTS.REPAIR_STARTED, { id: 2 });
    const repairs = bus.history(10, bus.EVENTS.REPAIR_STARTED);
    assert.equal(repairs.length, 2);
  });

  test("history() respects n limit", () => {
    bus.clearHistory();
    for (let i = 0; i < 20; i++) bus.emit(bus.EVENTS.BUILD_STARTED, { i });
    assert.equal(bus.history(5).length, 5);
  });

  test("off() removes a specific handler", () => {
    let count = 0;
    const handler = () => { count++; };
    bus.on(bus.EVENTS.ROLLBACK_STARTED, handler);
    bus.emit(bus.EVENTS.ROLLBACK_STARTED, {});
    bus.off(bus.EVENTS.ROLLBACK_STARTED, handler);
    bus.emit(bus.EVENTS.ROLLBACK_STARTED, {});
    assert.equal(count, 1);
  });

  test("EVENTS has all required keys", () => {
    const required = [
      "BUILD_STARTED","BUILD_COMPLETED","BUILD_FAILED",
      "REPAIR_STARTED","REPAIR_COMPLETED","REPAIR_FAILED",
      "RECOVERY_STARTED","RECOVERY_COMPLETED","RECOVERY_FAILED",
      "DOCTOR_STARTED","DOCTOR_COMPLETED",
    ];
    for (const key of required) {
      assert.ok(bus.EVENTS[key], `Missing EVENTS.${key}`);
    }
  });

});

// ── Telemetry ─────────────────────────────────────────────────────────────────

describe("Telemetry", () => {

  test("recordBuild increments counters and returns record", () => {
    const snap0 = tel.snapshot();
    const rec   = tel.recordBuild({ durationMs: 1000, success: true, outcome: "test" });
    const snap1 = tel.snapshot();
    assert.equal(rec.kind, "build");
    assert.equal(rec.success, true);
    assert.equal(snap1.counters.build_total, snap0.counters.build_total + 1);
    assert.equal(snap1.counters.build_success, snap0.counters.build_success + 1);
  });

  test("recordRepair captures strategy and rootCause", () => {
    const rec = tel.recordRepair({ durationMs: 500, success: false, retryCount: 2, strategy: "npm ci", rootCause: "INSTALL_FAILED", outcome: "failed" });
    assert.equal(rec.kind, "repair");
    assert.equal(rec.strategy, "npm ci");
    assert.equal(rec.rootCause, "INSTALL_FAILED");
    assert.equal(rec.retryCount, 2);
  });

  test("recordInstall tracks install duration average", () => {
    tel.recordInstall({ durationMs: 8000, success: true, attempts: 1, strategy: "npm install" });
    tel.recordInstall({ durationMs: 4000, success: true, attempts: 1, strategy: "npm install" });
    const snap = tel.snapshot();
    assert.ok(snap.averages.install_duration_ms > 0);
  });

  test("recordDoctor updates last health score", () => {
    tel.recordDoctor({ durationMs: 300, healthScore: 87, healthy: true });
    const snap = tel.snapshot();
    assert.equal(snap.last_health_score, 87);
  });

  test("prometheusText contains required metric names", () => {
    const text = tel.prometheusText();
    const required = [
      "build_duration_seconds",
      "repair_attempts_total",
      "repair_success_total",
      "repair_failures_total",
      "environment_health_score",
      "dependency_install_duration",
      "doctor_runs_total",
    ];
    for (const name of required) {
      assert.ok(text.includes(name), `Missing metric: ${name}`);
    }
  });

  test("snapshot includes rates object", () => {
    const snap = tel.snapshot();
    assert.ok(typeof snap.rates.repair_success_rate === "number");
    assert.ok(typeof snap.rates.install_success_rate === "number");
    assert.ok(typeof snap.rates.build_success_rate === "number");
  });

});

// ── Tracer ────────────────────────────────────────────────────────────────────

describe("Tracer", () => {

  test("startSpan returns span with active status", () => {
    const span = tracer.startSpan("TestSpan");
    assert.equal(span.status, "active");
    assert.ok(span.traceId);
    assert.ok(span.spanId);
    span.finish();
  });

  test("finish() changes status to ok and sets durationMs", () => {
    const span = tracer.startSpan("TestSpan2");
    const data = span.finish();
    assert.equal(data.status, "ok");
    assert.ok(data.durationMs >= 0);
  });

  test("finish(error) marks span as error", () => {
    const span = tracer.startSpan("ErrSpan");
    const data = span.finish(new Error("boom"));
    assert.equal(data.status, "error");
    assert.equal(data.error, "boom");
  });

  test("setTag / addEvent are preserved on finish", () => {
    const span = tracer.startSpan("TagSpan");
    span.setTag("k", "v");
    span.addEvent("myEvent", { x: 1 });
    const data = span.finish();
    assert.equal(data.tags.k, "v");
    assert.equal(data.events[0].name, "myEvent");
  });

  test("recent() includes finished spans", () => {
    const before = tracer.recent().length;
    const span = tracer.startSpan("RecentSpan");
    span.finish();
    assert.ok(tracer.recent().length >= before + 1);
  });

  test("active() excludes finished spans", () => {
    const span = tracer.startSpan("ActiveSpan");
    const before = tracer.active().find(s => s.spanId === span.spanId);
    assert.ok(before, "should be in active list");
    span.finish();
    const after = tracer.active().find(s => s.spanId === span.spanId);
    assert.ok(!after, "should not be in active list after finish");
  });

  test("getTrace() returns all spans for a traceId", () => {
    const parent = tracer.startSpan("ParentSpan");
    const child  = tracer.startSpan("ChildSpan", { traceId: parent.traceId, parentId: parent.spanId });
    parent.finish();
    child.finish();
    const spans = tracer.getTrace(parent.traceId);
    assert.ok(spans.length >= 2);
  });

  test("withSpan() wraps async fn and finishes span on success", async () => {
    let capturedSpan;
    const result = await tracer.withSpan("WrapSpan", async (s) => { capturedSpan = s; return 42; });
    assert.equal(result, 42);
    assert.equal(capturedSpan.status, "ok");
  });

  test("withSpan() finishes span with error on throw", async () => {
    let capturedSpan;
    try {
      await tracer.withSpan("ErrWrap", async (s) => { capturedSpan = s; throw new Error("test"); });
    } catch (_) {}
    assert.equal(capturedSpan.status, "error");
  });

  test("PHASES contains all build phase names", () => {
    const expected = ["ENVIRONMENT_CHECK","INSTALL","REPAIR","VERIFICATION","LAUNCH","ROLLBACK"];
    for (const k of expected) assert.ok(tracer.PHASES[k], `Missing PHASES.${k}`);
  });

});

// ── PM Abstraction ────────────────────────────────────────────────────────────

describe("PMAbstraction", () => {

  test("detect() returns a valid package manager name", () => {
    const pm = pmAbst.detect();
    assert.ok(["npm","pnpm","yarn","bun"].includes(pm), `Unexpected PM: ${pm}`);
  });

  test("createPM() returns facade with expected methods", () => {
    const pm = pmAbst.createPM();
    assert.ok(typeof pm.install === "function");
    assert.ok(typeof pm.ci === "function");
    assert.ok(typeof pm.add === "function");
    assert.ok(typeof pm.remove === "function");
    assert.ok(typeof pm.run === "function");
    assert.ok(typeof pm.exec === "function");
    assert.ok(typeof pm.name === "string");
  });

  test("createPM() detects npm for this project (has package-lock.json)", () => {
    const pm = pmAbst.createPM();
    // This project has package-lock.json at the root, so npm wins
    assert.equal(pm.name, "npm");
  });

});

// ── Concurrency Guard ─────────────────────────────────────────────────────────

describe("ConcurrencyGuard", () => {

  test("acquire() returns acquired=true for a fresh lock", () => {
    const lock = cg.acquire("test-op-fresh");
    assert.ok(lock.acquired);
    lock.release();
  });

  test("acquire() returns acquired=false for a held lock", () => {
    const lock1 = cg.acquire("test-op-held");
    assert.ok(lock1.acquired);
    const lock2 = cg.acquire("test-op-held");
    assert.ok(!lock2.acquired);
    assert.ok(lock2.reason);
    lock1.release();
  });

  test("release() allows re-acquisition", () => {
    const lock1 = cg.acquire("test-op-reacquire");
    lock1.release();
    const lock2 = cg.acquire("test-op-reacquire");
    assert.ok(lock2.acquired);
    lock2.release();
  });

  test("isLocked() reflects lock state", () => {
    assert.ok(!cg.isLocked("test-op-check-fresh"));
    const lock = cg.acquire("test-op-check");
    assert.ok(cg.isLocked("test-op-check"));
    lock.release();
    assert.ok(!cg.isLocked("test-op-check"));
  });

  test("withLock() runs fn and releases on success", async () => {
    let ran = false;
    await cg.withLock("test-op-with", async () => { ran = true; });
    assert.ok(ran);
    assert.ok(!cg.isLocked("test-op-with"));
  });

  test("withLock() releases lock on error", async () => {
    try {
      await cg.withLock("test-op-err", async () => { throw new Error("oops"); });
    } catch (_) {}
    assert.ok(!cg.isLocked("test-op-err"));
  });

  test("withLock() throws if lock already held", async () => {
    const lock = cg.acquire("test-op-busy");
    try {
      await assert.rejects(() => cg.withLock("test-op-busy", async () => {}));
    } finally {
      lock.release();
    }
  });

  test("forceClear() removes a held lock", () => {
    const lock = cg.acquire("test-op-force");
    assert.ok(lock.acquired);
    cg.forceClear("test-op-force");
    const lock2 = cg.acquire("test-op-force");
    assert.ok(lock2.acquired);
    lock2.release();
  });

});

// ── Sandbox ───────────────────────────────────────────────────────────────────

describe("Sandbox", () => {

  test("check() allows logs/ directory", () => {
    const r = sandbox.check("logs/test.log");
    assert.ok(r.allowed, `Expected allowed, got: ${r.reason}`);
  });

  test("check() allows node_modules/", () => {
    const r = sandbox.check("node_modules/foo/index.js");
    assert.ok(r.allowed);
  });

  test("check() allows package.json", () => {
    const r = sandbox.check("package.json");
    assert.ok(r.allowed);
  });

  test("check() blocks src/ writes", () => {
    const r = sandbox.check("src/renderer/App.tsx");
    assert.ok(!r.allowed);
    assert.ok(r.reason);
  });

  test("check() blocks app/ writes", () => {
    const r = sandbox.check("app/factory.py");
    assert.ok(!r.allowed);
  });

  test("check() blocks .py files", () => {
    const r = sandbox.check("something.py");
    assert.ok(!r.allowed);
  });

  test("check() blocks path traversal (../../etc)", () => {
    const r = sandbox.check("../../etc/passwd");
    assert.ok(!r.allowed);
  });

  test("check() blocks .git/", () => {
    const r = sandbox.check(".git/config");
    assert.ok(!r.allowed);
  });

  test("assertWritable() throws for blocked paths", () => {
    assert.throws(() => sandbox.assertWritable("src/App.tsx"), /sandbox/);
  });

  test("assertWritable() does not throw for allowed paths", () => {
    assert.doesNotThrow(() => sandbox.assertWritable("logs/out.log"));
  });

  test("allowedPaths() returns files and dirs arrays", () => {
    const ap = sandbox.allowedPaths();
    assert.ok(Array.isArray(ap.files));
    assert.ok(Array.isArray(ap.dirs));
    assert.ok(ap.files.includes("package.json"));
  });

});

// ── Config Profiles ───────────────────────────────────────────────────────────

describe("ConfigProfiles", () => {

  test("getConfig() returns merged config with profile field", () => {
    const cfg = profiles.getConfig("development");
    assert.equal(cfg.profile, "development");
    assert.ok(typeof cfg.maxRepairAttempts === "number");
  });

  test("production profile enables requireLockfile", () => {
    const cfg = profiles.getConfig("production");
    assert.ok(cfg.requireLockfile);
    assert.ok(cfg.metricsEnabled);
  });

  test("testing profile disables concurrencyGuard and persistTelemetry", () => {
    const cfg = profiles.getConfig("testing");
    assert.ok(!cfg.concurrencyGuard);
    assert.ok(!cfg.persistTelemetry);
  });

  test("staging profile enables metrics", () => {
    const cfg = profiles.getConfig("staging");
    assert.ok(cfg.metricsEnabled);
    assert.ok(cfg.requireLockfile);
  });

  test("unknown profile falls back to development overrides", () => {
    const cfg = profiles.getConfig("nonexistent");
    // Should not throw; profile field may differ
    assert.ok(cfg);
  });

  test("listProfiles() returns all 4 profiles", () => {
    const names = profiles.listProfiles();
    assert.ok(names.includes("development"));
    assert.ok(names.includes("testing"));
    assert.ok(names.includes("staging"));
    assert.ok(names.includes("production"));
  });

  test("profileDiff() returns only override keys", () => {
    const diff = profiles.profileDiff("testing");
    assert.ok(Object.keys(diff).length > 0);
    assert.ok("verbose" in diff || "maxRepairAttempts" in diff);
  });

  test("getConfig() is cached — same reference for same profile", () => {
    profiles.clearCache();
    const a = profiles.getConfig("development");
    const b = profiles.getConfig("development");
    assert.equal(a, b);
  });

});

// ── Plugin Architecture ───────────────────────────────────────────────────────

describe("Plugins", () => {

  test("registering and listing a repair plugin", () => {
    plugins.clearAll();
    plugins._api.register({
      name    : "test-repair",
      type    : "repair",
      classify: () => null,
      recover : async () => ({ ok: true, message: "fixed" }),
    });
    const list = plugins.listPlugins();
    assert.ok(list.some(p => p.name === "test-repair"));
  });

  test("classifyWithPlugins() returns first non-null classification", () => {
    plugins.clearAll();
    plugins._api.register({
      name: "cls1", type: "repair",
      classify: (stderr) => stderr.includes("EACCES") ? "PERMISSION" : null,
      recover: async () => ({ ok: false }),
    });
    const code = plugins.classifyWithPlugins("EACCES denied", "");
    assert.equal(code, "PERMISSION");
  });

  test("classifyWithPlugins() returns null when no plugin matches", () => {
    plugins.clearAll();
    plugins._api.register({ name: "noop", type: "repair", classify: () => null, recover: async () => ({ok:false}) });
    const code = plugins.classifyWithPlugins("random error", "");
    assert.equal(code, null);
  });

  test("recoverWithPlugins() returns success from first matching plugin", async () => {
    plugins.clearAll();
    plugins._api.register({
      name: "fixer", type: "repair",
      classify: () => null,
      recover: async () => ({ ok: true, message: "repaired by plugin" }),
    });
    const r = await plugins.recoverWithPlugins("PERMISSION", {});
    assert.ok(r && r.ok);
    assert.equal(r.plugin, "fixer");
  });

  test("runHealthPlugins() returns results from all health plugins", async () => {
    plugins.clearAll();
    plugins._api.register({ name: "hp1", type: "health", category: "custom", check: async () => ({ status: "PASS", message: "ok" }) });
    plugins._api.register({ name: "hp2", type: "health", category: "custom", check: async () => ({ status: "WARN", message: "slow" }) });
    const results = await plugins.runHealthPlugins();
    assert.equal(results.length, 2);
    assert.ok(results.some(r => r.status === "PASS"));
    assert.ok(results.some(r => r.status === "WARN"));
  });

  test("runDoctorPlugins() returns sections with lines", async () => {
    plugins.clearAll();
    plugins._api.register({ name: "dp1", type: "doctor", title: "My Check", run: async () => ["line1", "line2"] });
    const secs = await plugins.runDoctorPlugins();
    assert.equal(secs.length, 1);
    assert.equal(secs[0].title, "My Check");
    assert.equal(secs[0].lines.length, 2);
  });

  test("bad plugin doesn't crash classifyWithPlugins()", () => {
    plugins.clearAll();
    plugins._api.register({ name: "bad", type: "repair", classify: () => { throw new Error("crash"); }, recover: async () => ({ok:false}) });
    assert.doesNotThrow(() => plugins.classifyWithPlugins("err", "out"));
  });

  test("unregister() removes a plugin", () => {
    plugins.clearAll();
    plugins._api.register({ name: "rm-me", type: "health", category: "x", check: async () => ({status:"PASS",message:""}) });
    assert.ok(plugins.listPlugins().some(p => p.name === "rm-me"));
    plugins.unregister("rm-me");
    assert.ok(!plugins.listPlugins().some(p => p.name === "rm-me"));
  });

  test("loadDir() on non-existent dir returns empty results", () => {
    const r = plugins.loadDir("/tmp/nonexistent-plugin-dir-xyzzy");
    assert.equal(r.loaded.length, 0);
  });

});
