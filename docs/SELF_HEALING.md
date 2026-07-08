# Self-Healing Build System

The Self-Healing Build System automatically detects, classifies, and repairs common Node.js environment failures without manual intervention. It never modifies source files — only build configuration and `node_modules`.

## How It Works

When the dev server fails to start (or `npm run heal` is invoked), the system runs a **recovery pipeline** with four staged gates:

```
env-check → dependency-install → health-verify → done
```

Each gate must pass before the next begins. If `dependency-install` fails after all strategies are exhausted, the pipeline stops and reports the failure without touching source code.

## Recovery Strategies

The repair engine tries install strategies in order:

| # | Strategy | When used |
|---|---|---|
| 1 | `npm install` | Default |
| 2 | `npm install --cache /tmp/npm-cache` | Cache permission failure |
| 3 | `HOME=/tmp npm install` | Missing HOME directory |
| 4 | `npm ci` | Lockfile integrity check |
| 5 | `pnpm install` | pnpm available on PATH |
| 6 | `yarn install` | yarn available on PATH |
| 7 | `bun install` | bun available on PATH |

## Failure Classification

Every failure is classified before recovery is attempted:

| Class | Trigger | Recovery |
|---|---|---|
| `PERMISSION` | `EACCES` in stderr | Fix npm cache dir permissions |
| `MISSING_HOME` | `HOME` env missing | Set `HOME=/tmp` and retry |
| `NO_CACHE_DIR` | `ENOENT` on cache path | Create fallback cache |
| `READONLY_FS` | `EROFS` in stderr | Redirect cache to `/tmp` |
| `INSTALL_FAILED` | Exit code ≠ 0 | Cycle through install strategies |
| `MISSING_MODULES` | `Cannot find module` | Run install |
| `MISSING_SCRIPT` | `Missing script` | Check `package.json` |
| `MISSING_PORT` | `EADDRINUSE` | Report port conflict |
| `SYNTAX_ERROR` | `SyntaxError` in output | Escalate (can't auto-fix) |

## Commands

```bash
npm run heal    # Run the repair engine directly
npm run doctor  # Full environment diagnostics (no repair)
```

## Safety Guarantees

- **No source file modifications**: the sandbox layer blocks writes to `src/`, `app/`, `.git/`, and all `.py`, `.ts`, `.tsx` files.
- **Backup before modify**: any config file (`package.json`, `.npmrc`, etc.) is backed up to `backups/` before modification.
- **Max retry guard**: each failure class is retried at most 3 times before the engine gives up.
- **No sudo**: all recovery operations are designed to succeed without elevated privileges.

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Recovery succeeded |
| 1 | Recovery completed with warnings |
| 2 | Recovery failed — manual intervention needed |
