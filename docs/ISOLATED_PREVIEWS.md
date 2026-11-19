# Isolated App Builder previews and durable workspaces

This change is code and configuration, not a production activation. Do not apply
its Blueprint or start paid sandbox sessions without deployment authorization.

## Runtime boundary

App Builder's `/api/projects/{id}/run` and `/run/stream` use `vercel-sandbox==1.0.0`.
They never dispatch generated code to host drivers, even when provider setup
fails. Existing ownership guards apply to Run, Stop, status and the retired
proxy. Generic same-origin navigation returns 410 **after** checking ownership.
The opaque commerce preview retains only its authenticated, path-limited RPC
bridge. That bridge targets the isolated VM, never host loopback; it forwards no
subscription headers, bearer tokens or platform cookies. Its responses are
non-executable attachments with nosniff, not same-origin HTML or JavaScript.

Each run creates a nonpersistent Vercel microVM with one vCPU, a 300-second
provider-enforced lifetime and no inherited host environment. The backend-only
credentials `VERCEL_TOKEN`, `VERCEL_TEAM_ID` and `VERCEL_PROJECT_ID` authorize the
control client; they are not injected into the VM. Missing configuration fails
closed on Run and does not prevent the rest of Flow from starting.

Only workspace files are uploaded (maximum 1000 files / 20 MB). Symlinks are
rejected; `.env*` files other than `.env.example`, `.git`, virtual environments
and `node_modules` are omitted. Keep all production credentials outside project
source. Project files must not embed production secrets.

Egress starts at `deny-all`. Node installation temporarily permits only
`registry.npmjs.org`, with npm lifecycle scripts disabled. Python installation
permits only `pypi.org` and `files.pythonhosted.org`. Egress is revoked before
starting the app. Private packages, Git dependencies, downloads from other hosts
and runtime external APIs are intentionally unsupported by this first version.
Do not replace this with allow-all to make an installation succeed.

Supported previews: static HTML; Vite-style dev scripts; Node start scripts that
respect `PORT=8080`; FastAPI and Flask; bounded Python scripts. A custom command
is rejected. Other frameworks may need a dedicated adapter. HTTP preview
responses and request bodies are capped at 10 MB; WebSocket/HMR proxying is not
implemented. A new Run starts a new VM from the durable source files. Runtime
writes inside a VM are temporary, except the commerce state described below.

The VM exposes only a trusted gateway on port 3000. A random per-run bootstrap
capability sets a Secure, HttpOnly, SameSite=None, Partitioned cookie and
redirects away from the capability URL. The gateway requires that cookie on
subsequent requests; another session's token is rejected. Its upstream app
listens on port 8080. Platform auth headers and the gateway cookie are stripped
before requests reach generated code. The preview runs on an approved
`https://*.vercel.run` origin, never the Flow origin. The UI suppresses referrers,
opens new windows without an opener and hides the capability from its toolbar
and event timeline. Browser support for partitioned third-party cookies is
required for embedded previews; Open can be used in a separate tab.

The capability is a temporary shareable secret, not platform authentication.
Anyone given that URL can view the preview until it is stopped or expires.
The VM is not a persistent production deployment. Generated code shares its
own VM with its preview gateway; this boundary isolates the **platform and other
projects**, not components inside the same preview VM.

The backend holds at most four VMs per process and serializes operations for
one project. It retains cleanup handles for retries on provider errors. Startup
has a 180-second deadline; commands have 90-second limits. Stop and shutdown
destroy the VM. The provider's hard lifetime still applies if the backend
crashes. Session handles are in memory: use the current single-worker topology;
a backend restart requires a new Run and cannot extend an old VM's lifetime.
A shared session registry is required before adding workers/instances.

## Persistent storage activation — separate deployment step

The Blueprint declares a 5 GB disk mounted at `/app/workspaces`, and sets
`WORKSPACES_DIR` to that same path. This matches the Docker image's existing
workspace directory. `REQUIRE_WORKSPACE_MOUNT=true` makes startup fail if the
path is not a mount, and startup verifies a flushed write as the application user
without leaving probe files. Do not enable this flag for local ephemeral dev.
It preserves **new writes under the mount** across deploys
and restarts after the disk is attached. It does not automatically recover
existing ephemeral data, and editing `render.yaml` does not attach a disk.

Before applying any deployment:

1. Back up every existing project's workspace from the currently running service
   to approved private storage. Preserve UUID directories and verify file counts
   and checksums. Do this **before** adding the disk: that action triggers a
   deploy and the old ephemeral instance may be lost. Do not put project source
   or secrets into public artifacts, repository commits or chat logs.
2. Record the exact target Render service. Fix its mismatched
   `RENDER_DEPLOY_HOOK_URL` separately; never bypass the workflow target check.
3. With authorization for the storage cost and deployment, attach/apply the disk.
   A disk-backed service is single-instance and loses zero-downtime deploys;
   schedule the interruption. Verify the non-root `axon` user (UID 1001) can
   write the mounted path. Correct ownership through authorized service access
   if required; never switch the application to root to work around it.
4. Restore the approved backup into `/app/workspaces`, preserving ownership.
   Compare restored checksums with the backup and verify a project can be
   exported. Do not remove the backup until recovery is verified.
5. Configure backend-only Sandbox credentials in Render. Never use `VITE_*`
   variables or commit credentials. Setting them does not itself start a VM.
6. Deploy the backend and frontend changes together. A new frontend rejects an
   old backend's same-origin/blob preview events with an update message.
7. Run the acceptance checks below using test-owned data. Confirm the running
   backend SHA and retain evidence before calling the integration activated.

Disk data is not a source-control/version-history system. Atomic multi-file
modification and rollback remain a separate follow-up. Use private backups;
do not rely exclusively on platform disk snapshots.

Current references consulted for configuration:
- https://render.com/docs/disks
- https://render.com/docs/blueprint-spec
- Python package `vercel-sandbox==1.0.0` public API signatures and metadata

## Verification

Local regression tests use provider mocks and fixture HTTP servers, not paid
VMs, live credentials, a production database or production project data:

```sh
pytest tests/test_isolated_previews.py tests/test_preview_gateway.py tests/test_build_stream_edge_cases.py tests/security/test_api_security.py tests/test_projects.py -q
npm run typecheck
npm run lint:strict
npx vitest run src/renderer/features/app-builder/__tests__
npm run build
```

Deployment acceptance (requires authorized activation):
- A test user builds HTML and Node/Python fixtures and previews them in a browser.
- Browser requests carry only preview credentials to the separate preview origin.
- An unauthenticated visit/another project's capability is rejected; the platform
  still refuses another user's project Run/Stop/export.
- Test-generated code cannot see control-plane secrets or other workspaces;
  unapproved runtime network access fails.
- Stop removes access; refresh or a new Run after expiry behaves predictably;
  network/deletion failures retain an actionable Stop retry.
- Exported workspace checksums survive a service restart and another deploy.
- `/health` reports the approved SHA and the relevant deployed checks pass.

No live provider execution or Render restart was performed by local tests.


## Commerce integration with current main

The existing opaque storefront and its project-scoped message bridge are
preserved. Store requests use an owner-authenticated, allowlisted RPC path to the
VM gateway. Only the per-preview capability and that project's store cookie
cross the boundary. Response cookies are restricted to flow_store_session and
are scoped to that project's proxy path. Origin/JSON checks remain enforced by
the store. Redirects are not followed. Request and response sizes are bounded.
Only the shipped verified storefront client is evaluated by the opaque preview.

The owner setup token is read from the active VM, not a stale host-side file.
The backend snapshots the store's SQLite database using SQLite backup **inside
the VM**, then atomically writes bounded bytes to data/store.sqlite3 under the
project's durable workspace. It flushes file and directory metadata. The initial
initialized database is saved before server_ready; each commerce mutation is
saved before its result is returned to the UI. A new VM receives the saved data.
The host never imports or executes the generated store backend for this work.
Failed saves remain visible and prevent Stop from discarding dirty state. A
backend/provider crash or hard VM expiry can still lose mutations that have not
been acknowledged as saved; this is a preview, not a production transaction host.

Direct Open is withheld for commerce so the supported UI uses the saving bridge.
Storefront mutations made manually against the VM URL are outside this supported
persistence path. Runtime-written files for arbitrary apps remain ephemeral.
Activation tests must additionally verify owner setup, inventory, customer login,
checkout, and order history across VM replacement and service restart. Existing
source exports continue to exclude runtime databases and credentials.


## Read-only configuration check

`app/activation_check.py` is a standalone, standard-library-only check. Run it
inside the intended service, as its normal application user, using a reviewed
40-character release SHA and the confirmed service ID:

```sh
python -B /app/app/activation_check.py \
  --expected-service srv-d6705koboq4c7384n0cg \
  --expected-commit REVIEWED_40_CHARACTER_RELEASE_SHA
```

Replace the SHA placeholder; do not compare the running SHA to itself or assume
that a successful check on a developer computer represents the Render service.
The current production image may not include this new file. A reviewed copy can
also be supplied on standard input using `python -B -` with the same arguments;
that does not require saving it into production or deploying merely to inspect
configuration. Use the secure service Shell, not chat, for any secret setup.

The tool reports only:
- Whether each required Sandbox variable is nonempty, never its value.
- Whether the service and release match the explicitly reviewed identifiers.
- Whether mount enforcement is enabled and the workspace root is a real mount.
- Root directory counts, without filenames or reading project/customer content.
- Whether the pinned Sandbox SDK is installed, without importing it.

It does not import Flow, initialize schemas, create files, run a write probe,
start a VM, access a database or call a provider. It makes no network requests.
`-B` prevents Python bytecode files. `os.access` is only a permission hint and is
explicitly INCONCLUSIVE for actual writes. A configuration PASS (exit 0) is not
runtime verification, a verified backup, or deployment authorization. FAIL exits
1; missing evidence exits 2. Backup/restore, actual writes, cross-restart
persistence and the customer journey remain separate acceptance checks.

Operational observation on 2026-11-19: the confirmed Render service was live on
`1d79b1323347a4f1ac3dbf52adabaead0e7c0698`; PR #63 remained a draft. The service's
actual auto-deploy setting was `checksPass`, despite `autoDeploy: false` in the
Blueprint. Recheck this before authorizing a merge: merging a green PR can deploy
before disk/data/provider preparation. No production setting was changed during
that inspection. The connector did not expose disk or secret-presence evidence;
the browser sign-in was not completed, so those items remain unverified. This
check prepares a way to collect that evidence without disclosing secret values.
