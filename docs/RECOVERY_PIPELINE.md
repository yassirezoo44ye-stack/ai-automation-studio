# Recovery Pipeline

The recovery pipeline is the orchestration layer that coordinates all self-healing subsystems into a single observable sequence.

## Sequence Diagram

```
Caller (dev server / CLI)
  │
  ▼
ConcurrencyGuard.acquire("recovery")   ← blocks duplicate runs
  │
  ▼
EventBus.emit(RecoveryStarted)
Tracer.startSpan("Verification")
  │
  ├─ Stage 1: EnvironmentCheck
  │     env-checker.snapshot()
  │     → Node version, PM detection, permissions, ports
  │
  ├─ Stage 2: DependencyInstall         (skipped if node_modules exists)
  │     RepairEngine.installDependencies()
  │     → tries up to 7 strategies
  │     → Telemetry.recordInstall()
  │     → EventBus.emit(InstallStarted / InstallCompleted / InstallFailed)
  │
  ├─ Stage 3: HealthVerify
  │     HealthCheck.run()
  │     → filesystem, permissions, runtime, dependencies, ports, environment
  │
  └─ Stage 4: Done
        Tracer.span.finish()
        Telemetry.recordBuild()
        EventBus.emit(RecoveryCompleted / RecoveryFailed)
        ConcurrencyGuard.release()
```

## Stage Gate Rules

A stage passes if its primary check returns a truthy `ok` or `healthy` field. Warnings do not block the pipeline; only hard failures do.

| Stage | Pass condition | On failure |
|---|---|---|
| env-check | Node ≥18 AND PM detected | Pipeline stops |
| dependency-install | `node_modules` exists or install succeeds | Pipeline stops |
| health-verify | `healthReport.healthy === true` | Pipeline reports unhealthy but does not retry |
| done | Always reached | Marks pipeline as complete |

## Concurrency Protection

Only one recovery pipeline may run at a time. A second call while the first is running returns immediately:

```json
{ "ok": false, "skipped": true, "reason": "Recovery already running: locked by PID 1234" }
```

The lock is file-based (`.locks/recovery.lock`) and expires after 10 minutes to prevent stale locks from blocking recovery after a crash.

## API

```js
const { runPipeline, recoverFailure, listBackups, restoreBackup } = require("./tools/recovery-manager.cjs");

// Run the full pipeline
const result = await runPipeline({ silent: false, maxAttempts: 2 });
// result: { ok, stages, durationMs, healthReport, ts }

// Recover from a single classified failure
const r = await recoverFailure({ stderr: "EACCES permission denied", stdout: "" });

// Backup management
const backups = listBackups();
await restoreBackup(backups[0].id);
```

## Observability

Every pipeline run emits:
- **Spans**: `Verification` (wraps entire pipeline), nested `EnvironmentCheck`, `Install`, `Repair`
- **Events**: `RecoveryStarted`, `RecoveryCompleted` or `RecoveryFailed`
- **Telemetry**: `build_total`, `build_success`, `build_duration_ms` counters and averages
- **Logs**: structured JSON lines to `logs/runtime.log`
