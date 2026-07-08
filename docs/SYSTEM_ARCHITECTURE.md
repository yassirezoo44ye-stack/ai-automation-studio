# Self-Healing Build System — System Architecture

## Module Map

```
tools/
├── logger.cjs            Structured JSON-line logging (runtime, install, build, errors)
├── backup-manager.cjs    Config file backup/restore with allowlist + denylist
├── env-checker.cjs       Environment snapshot (Node, PM, permissions, ports, vars)
├── health-check.cjs      Scored health report across 6 categories
├── repair-engine.cjs     Failure classifier + 7-strategy self-healing installer
├── recovery-manager.cjs  Pipeline orchestrator (env → install → health → done)
├── doctor.cjs            CLI diagnostic tool with 13 check sections
│
├── event-bus.cjs         Typed event bus (11 event types, ring buffer, jsonl persist)
├── telemetry.cjs         Operation recorder + Prometheus metrics HTTP endpoint
├── tracer.cjs            OpenTelemetry-compatible span tracer (ring buffer)
├── pm-abstraction.cjs    Unified npm/pnpm/yarn/bun interface
├── concurrency-guard.cjs File-lock + in-process mutex (prevents duplicate runs)
├── sandbox.cjs           Path validation (blocks writes outside allowlist)
├── config-profiles.cjs   dev/test/staging/production profile overrides
└── plugins.cjs           Plugin loader for repair/health/doctor/installer plugins
```

## Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      CLI / npm scripts                               │
│              npm run doctor  |  npm run heal                        │
└───────────────────┬─────────────────────────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────────────────────────┐
│               Orchestration Layer                                    │
│                 recovery-manager.cjs                                │
│     ConcurrencyGuard → EventBus → Tracer → Pipeline → Telemetry    │
└───────────────────┬─────────────────────────────────────────────────┘
                    │ stages
         ┌──────────┼────────────┐
         │          │            │
┌────────▼──┐  ┌────▼────┐  ┌───▼────────┐
│env-checker│  │ repair  │  │health-check│
│   .cjs    │  │-engine  │  │   .cjs     │
└───────────┘  │  .cjs   │  └────────────┘
               └────┬────┘
                    │ strategies
               ┌────▼──────────────────┐
               │  pm-abstraction.cjs   │
               │  npm/pnpm/yarn/bun    │
               └───────────────────────┘

Cross-cutting concerns (used by all layers):
  sandbox.cjs          — blocks writes to source files
  backup-manager.cjs   — backup before any config change
  logger.cjs           — structured logging
  event-bus.cjs        — typed events for monitoring/plugins
  telemetry.cjs        — metrics counters and Prometheus output
  tracer.cjs           — span-based distributed tracing
  concurrency-guard.cjs— prevents duplicate repair runs
  config-profiles.cjs  — environment-specific settings
  plugins.cjs          — extensibility layer
```

## Data Flow: Recovery Pipeline

```
1.  npm run heal
2.  recovery-manager.runPipeline()
3.  concurrency-guard.acquire("recovery")       → blocks if already running
4.  bus.emit(RECOVERY_STARTED)
5.  tracer.startSpan("Verification")
6.  env-checker.snapshot()                      → Stage 1
7.  repair-engine.installDependencies()         → Stage 2 (if needed)
      pm-abstraction.createPM().install()
      sandbox.assertWritable(path)              → checked before any write
      backup-manager.create(files, reason)      → backup before patch
8.  health-check.run()                          → Stage 3
9.  tracer.span.finish()
10. telemetry.recordBuild({ durationMs, ok })
11. bus.emit(RECOVERY_COMPLETED | RECOVERY_FAILED)
12. concurrency-guard.release()
```

## Event Flow

```
BuildStarted        — dev server starting
InstallStarted      — npm install beginning
InstallCompleted    — install succeeded
InstallFailed       — install failed (all strategies)
RepairStarted       — repair attempt beginning
RepairCompleted     — repair succeeded
RepairFailed        — repair could not fix the issue
RecoveryStarted     — pipeline beginning
RecoveryCompleted   — pipeline succeeded
RecoveryFailed      — pipeline failed
DoctorStarted       — doctor starting
DoctorCompleted     — doctor finished
RollbackStarted     — rollback beginning
RollbackCompleted   — rollback succeeded
RollbackFailed      — rollback failed
```

## File Layout (runtime artifacts)

```
backups/
├── manifest.json           List of all backups
└── <id>/                   One directory per backup
    ├── meta.json           {id, reason, files, created}
    └── <file>              Backed-up file content

logs/
├── runtime.log             Structured JSON lines (operations)
├── install.log             Install command output
├── build.log               Build output
├── errors.log              Error records
├── events.jsonl            Event bus history
├── telemetry.jsonl         Telemetry records
└── traces.jsonl            Span records

.locks/
└── <op>.lock               File locks (e.g. recovery.lock)
```

## Performance Targets

| Operation | Target | Notes |
|---|---|---|
| `npm run doctor` | < 2 seconds | All network checks are parallel |
| `health-check.run()` | < 1 second | No network calls |
| Recovery overhead | < 5% of build time | Events/spans are async |
| Memory usage | < 100 MB | Ring buffers capped at 500–2000 entries |

## Configuration

Configuration is read from environment variables and `BUILD_PROFILE`:

```bash
BUILD_PROFILE=production npm run doctor   # use production profile
BUILD_PROFILE=testing node --test tests/  # use testing profile (no file locks)
```

See [SELF_HEALING.md](./SELF_HEALING.md) for recovery details,
[DOCTOR_GUIDE.md](./DOCTOR_GUIDE.md) for diagnostic output interpretation,
[SECURITY_MODEL.md](./SECURITY_MODEL.md) for security boundaries, and
[PLUGIN_DEVELOPMENT.md](./PLUGIN_DEVELOPMENT.md) for extending the system.
