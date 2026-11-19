# Real execution across Flow and generated apps

Flow's completion messages must describe observable results. Creating a plan,
writing files, starting a process, passing a journey, and publishing are separate
facts. Never infer later facts from earlier ones.

## Generated applications

Both build endpoints validate delivered files and startup metadata. Requests with
business transactions, database tables, or an approved backend stack must include
server source, persistence implementation, and dependency configuration. Truncated
streams and frontend-only transactional outputs emit an error, not `done`.
Business apps also require interface files unless an API-only scope was explicitly
requested or approved. Python files must parse successfully; backend/database
evidence comes from application calls and model declarations, excluding tests and
fixtures. Imports, comments and descriptive strings do not supply Python backend
or database implementations. Recognized Python, Node and Uvicorn startup entries
must be delivered, and npm startup scripts must exist in the root package.json.
These checks parse source without importing or executing generated code. They do
not establish route behavior, database connectivity, integration readiness or that
every framework/startup-command variant is supported.
This is a structural minimum, not a security audit or proof of runtime behavior.
The API reports `status: generated`, `structure_checked: true`,
`runtime_verified: false`, `deployed: false`. The UI says files were generated.
Owners use the real inference provider; identity never silently selects a mock
application generator. Existing owner quota policy remains separate from provider
selection. External integrations still require credentials and actual testing.

The commerce contract has an independently tested frontend → authenticated proxy
→ backend → SQLite order journey. It supports cash on delivery. Other arbitrary
app types still require their own runtime and end-to-end verification before any
readiness claim. See RUNNABLE_COMMERCE.md for the verified scope and deployment
requirements. Failure preserves generated files for inspection and repair.

## Flow operations

- Published Feed records come from saved source records; interactions wait for
  server confirmation. Failed duplication creates no placeholder success.
- Automation supports AI, email, approval, and explicit noop steps. Unknown step
  kinds raise and become failed runs through the workflow engine; they cannot
  silently pass as noop. Explicit noop is not evidence of an external action.
- Deployment commands without an installed driver return
  `DEPLOY_DRIVER_UNAVAILABLE` with success false. Exporting an archive is not
  evidence of hosting a live app.
- Keep organization/owner checks, approvals, quotas, and error recovery in every
  implementation. Device actions need device acknowledgement; email/social actions
  need the provider result; durable business mutations need committed storage.

This change establishes and enforces these boundaries at the audited build,
workflow-dispatch, deploy-command, and Feed paths. It does not certify every
integration or every screen as production-ready. Expand verification journey by
journey, without adding dashboard clutter or mock activity to the product.

## Release pipeline

After production health confirms the exact source SHA, CI generates release notes
without changing tracked files and tags that verified commit. It does not push a
release commit to protected main. Changelog edits can use the normal PR process;
the GitHub Release carries the automated notes. A retry reuses a tag at the same
commit, and a conflicting tag is rejected without overwriting history. Release
publication remains separate from evidence that the production deployment is live.
