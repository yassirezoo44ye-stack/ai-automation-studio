# Runnable commerce delivery, not a visual mock

Requests for an online/e-commerce store or متجر use `flow-commerce-cod-v1` in the
existing authenticated build/plan and streaming-build paths. Authentication,
project ownership, quotas/rate limits and safe workspace paths remain in force.
The regular build endpoint exports the same files. This scaffold does not call
DevMock or an LLM and needs no AI credits after approval.

The approved plan states its actual stack: Arabic RTL HTML/CSS/JavaScript,
FastAPI and SQLite, with cash-on-delivery checkout. It describes only implemented
pages/tables/routes and has no configured external integrations. An old or edited
plan advertising React/Express/MongoDB, card payments or email is rejected rather
than silently producing something else. Regenerate and approve the new plan.
Customized existing entry points are preserved; use a new project.

## Delivered work

- Browsable/searchable inventory; cart with quantity/remove actions.
- Customer registration/login/logout; salted PBKDF2 hashes and hashed, expiring
  HTTP-only session tokens; login attempt limits.
- Server-priced checkout, transactional stock reservation and per-customer
  idempotency; no overselling or caller-supplied price/owner/admin privileges.
- Durable order history scoped to the signed-in customer.
- Host-authorized one-time owner setup; role-protected product management and
  order transitions, with stock restored exactly once on eligible cancellation.
- Root Python entry point, dependencies, settings example, README and export tests.

The store starts with no invented products or orders. The owner adds actual
products/stock/prices and supplies delivery, collection, policies and hosting.
COD creates an order, not a payment confirmation or revenue guarantee. Stripe,
Payfort, email/SMS, automated shipping, taxes and refunds are NOT implemented.
Their future adapters must verify actual provider events before reporting success.

## Running and preview

The detector identifies FastAPI; Flow runs the store in an isolated Vercel VM,
never on the API host. Backend-only Sandbox credentials are required and missing
configuration fails closed. The preview has a five-minute lifetime. The opaque
preview's authenticated RPC bridge saves SQLite state to the project's durable
workspace before acknowledging mutations, and new VMs receive the saved state.
Failed saves remain visible; manually mutating the separate VM URL bypasses this
supported persistence bridge. Exported projects also run directly with
`python main.py`, honoring PORT. SQLite remains single-instance; durable public
hosting requires a persistent volume and backups. Public deployment is a separate
explicit action. See ISOLATED_PREVIEWS.md for activation and failure boundaries.

On first run, a 0600 `data/owner-setup.txt` file contains the one-time token, stored
as a hash in the database. The authenticated project owner can reveal the active VM's token through
Store owner setup. In the store's Account section, use it to initialize ownership.
It is deleted after successful setup; restarting an unconfigured store rotates it.
Public storefront APIs never return that token. Host CLI setup is also available.

The in-Flow preview uses an opaque sandbox with a project-scoped message bridge.
It never exposes Flow tokens, parent DOM or parent storage to generated scripts.
Only the shipped, verified storefront client is previewed here, using public static client assets under the existing CSP; modified client
code can be exported and run on its own host. Server responses remain authoritative.
Saved commerce projects are recognized by their manifest and reopen with the correct runtime state. Store API requests are proxied to the isolated VM with Flow ownership
authentication; only the preview capability and project store cookie reach the
VM. Flow auth headers are never forwarded. Bridge responses are non-executable
attachments with nosniff, including storefront HTML and JavaScript fetched as text. Cookies are project-scoped;
only the store session is forwarded in this preview mode. Standalone storage keeps
cart state; opaque preview keeps the cart in memory while orders persist in SQLite.

## Feed and capability claims

Feed still loads published creations and study resources, not sample fallback
items. Publisher display names come from saved user records (never email), and
unknown publishers are not relabeled Flow Platform. Published-item actions open
actual item details rather than manufacturing a fresh application from its text.
Likes/saves update from the server response; failures are visible, not fake counts.
Source-clone failures and unsupported duplication return 409 and never insert an
empty replacement card. No private project is published automatically.

The public capabilities section now highlights saved skills/plans/results,
trackable execution, runnable COD stores, configured providers and published work,
without promising autonomous income, live card payments or universal integrations.

## Evidence

Store tests use temporary SQLite databases and verify ownership, privileges,
password/session handling, bootstrap token consumption, server pricing, replay,
stock contention, cancellation, persisted history and same-origin JSON writes.
Route tests verify plan/file consistency, no model/mock invocation, preserving
existing work and owner-only setup access. Proxy tests verify token stripping and
cookie scoping. Bootstrap also revokes pre-existing sessions if the owner had previously registered as a customer. Clone-failure tests assert no placeholder insertion.
Previous host-driver browser verification covered the exported application's
owner setup → inventory → customer → checkout → history after reload and the
opaque frame. The new isolated driver requires its own authorized live-provider
acceptance run; local isolation tests use provider mocks and fixture HTTP servers.
The new regression tests verify bounded durable snapshots, restoration on the
next upload, save-before-response, credential stripping, cookie scoping, and
retaining unsaved state on failed Stop. They do not certify production activation.
