# Security Model

The Self-Healing Build System is designed to operate safely in an untrusted build environment. This document describes the security boundaries enforced at every layer.

## Threat Model

The build system's primary concern is **accidental or malicious modification of project files** during recovery. The threat actors are:

1. A buggy repair plugin writing to the wrong path
2. A recovery strategy running a shell command that modifies source code
3. A malicious `package.json` script that the installer runs during `npm install`

## Sandbox Layer (`tools/sandbox.cjs`)

Every write operation must pass through the sandbox before execution. The sandbox enforces two lists:

### Allowlist (writes permitted)
- `package.json`, `package-lock.json`, `.npmrc`, `.nvmrc`, `.node-version`
- `vite.config.ts`, `vite.config.js`, `tsconfig.json`, `tsconfig.node.json`
- `.env.local`, `.env.development`
- `eslint.config.js`, `eslint.config.mjs`
- `logs/`, `.locks/`, `backups/`, `node_modules/`

### Blocklist (writes always denied, even if in allowlist)
- `src/` — frontend source
- `app/` — Python backend source
- `migrations/`, `alembic/` — database migrations
- `.git/` — git history
- `.github/` — CI workflows
- `tests/` — test suite
- `*.py`, `*.ts`, `*.tsx` — source file extensions
- `Dockerfile`, `render.yaml` — deployment config
- `*.pem`, `*.key`, `*.p12`, `id_rsa`, `id_ed25519` — credentials

### Path Traversal Prevention

All paths are `path.resolve()`'d to absolute form and compared against the project root. Any path whose relative form starts with `..` is blocked with:

```
[sandbox] Write blocked: "../../etc/passwd" — path escapes project root.
```

## Backup-Before-Modify Policy

Any config file modification via `repair-engine.cjs/patchConfig()` automatically:
1. Creates a timestamped backup in `backups/<id>/`
2. Records the backup manifest to `backups/manifest.json`
3. Only then writes the patched content

Rollback restores from the backup and verifies the restored file's hash.

## No-Sudo Policy

All repair operations are designed to succeed without `sudo`:
- Cache directory fallback to `/tmp/npm-cache` instead of system paths
- `HOME=/tmp` override for broken HOME environments
- `node_modules` created in project root (no global install)

The system never calls `sudo`, `su`, `chmod +s`, or any setuid operation.

## Secret Protection

The following files are never backed up, read by the repair engine, or logged:
- `.env` (root — may contain secrets)
- `*.pem`, `*.key`, `*.p12`
- `id_rsa`, `id_ed25519`

Environment variables containing `SECRET`, `TOKEN`, `KEY`, or `PASSWORD` in their name are redacted in log output.

## Concurrency Protection

File-based locks prevent multiple repair processes from running simultaneously, which would cause race conditions on `package.json` and `node_modules`. Lock files are stored in `.locks/` and auto-expire after 10 minutes.

## Plugin Security

- Plugins are loaded from configured directories only (default: `./tools/plugins`)
- Plugin execution is wrapped in `try/catch` — a plugin crash cannot take down recovery
- Repair plugins that write files must use `sandbox.assertWritable()` or their writes will be blocked

## Audit Trail

All repair and recovery actions are logged to:
- `logs/runtime.log` — structured JSON lines (no secrets)
- `logs/telemetry.jsonl` — timing and outcome records
- `logs/traces.jsonl` — OpenTelemetry spans
- `logs/events.jsonl` — event bus history

These logs contain operation metadata only, never file contents or environment variable values.
