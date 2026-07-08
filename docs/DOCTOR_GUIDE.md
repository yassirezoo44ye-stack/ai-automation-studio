# Doctor Guide

`npm run doctor` is a comprehensive environment diagnostic tool that checks every aspect of the project's build environment and prints a scored health report.

## Usage

```bash
npm run doctor          # Full diagnostic
node tools/doctor.cjs   # Equivalent, direct invocation
```

## Output Sections

| Section | What is checked |
|---|---|
| **Overview** | Health score (0–100) and overall status |
| **Runtime snapshot** | Node version, package manager, HOME/CWD/tmp permissions |
| **Dependency integrity** | `package.json` validity, lockfile, `node_modules`, `vite.config`, `tsconfig` |
| **Scripts** | All `package.json` scripts (`dev`, `build`, `test`, etc.) |
| **Environment variables** | Required vs optional env vars |
| **Port availability** | Ports 3000, 5173, 8000, 8080 |
| **Backup status** | Recent config backups |
| **node_modules integrity** | Package count, corrupted package detection |
| **ESM / CJS compatibility** | `package.json type`, stray `.js` files in an ESM project |
| **Disk space** | Available disk space on the current partition |
| **Network** | Reachability of npm registry and GitHub |
| **Build system telemetry** | Doctor runs, repair success rate, average build duration |
| **Build readiness** | Final verdict with suggested fixes |

## Health Score

The score is computed from health check probes across 6 categories:

- Each `PASS` probe contributes to the score.
- `WARN` probes reduce the score slightly.
- `FAIL` probes reduce the score significantly.

**Score thresholds:**

| Score | Colour | Interpretation |
|---|---|---|
| 90–100 | Green | Production-ready |
| 70–89 | Yellow | Warnings present, build may succeed |
| 0–69 | Red | Critical issues, build likely to fail |

## Exit Codes

| Code | Condition |
|---|---|
| 0 | All checks pass (score ≥ 90, no failures, no warnings) |
| 1 | Warnings present but no critical failures |
| 2 | One or more critical failures |

## Interpreting Common Failures

### `npm cache: not writable`
Run `npm cache clean --force` or set a writable cache directory:
```bash
npm config set cache /tmp/npm-cache
```

### `node_modules: missing`
```bash
npm install
```

### `port 5173: in use`
Another Vite server is running. Kill it:
```bash
# Find the PID
npx kill-port 5173
```

### `ENOENT vite.config.ts`
The Vite config is missing. Restore from backup:
```bash
node -e "const r=require('./tools/recovery-manager.cjs'); const bs=r.listBackups(); console.log(bs[0]);"
node -e "require('./tools/recovery-manager.cjs').restoreBackup('BACKUP_ID')"
```

### `ESM/CJS mismatch: .js files in tools/`
All tool files must use `.cjs` extension when `package.json` has `"type": "module"`.

## Telemetry

Each doctor run records:
- Duration (milliseconds)
- Health score
- Whether the environment is healthy

This telemetry is visible in the `Build System Telemetry` section on subsequent runs, and is exposed on the Prometheus metrics endpoint when enabled.
