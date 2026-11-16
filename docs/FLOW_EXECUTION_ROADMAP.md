# Flow implementation scope

This roadmap separates delivered behavior from future work. Existence of a page,
router or skill is not evidence that a component is production-ready.

## Current increment

- Nine instruction-based skills integrated into chat and AgentOS (previous release).
- Durable idea → reviewed plan → project → linked tasks → restored progress.
- Durable approved skill/inspection runs with PostgreSQL dispatch, cancellation, result artifacts and interruption recovery.
- Ownership-scoped plan access, atomic saves, replay protection, dependency guards,
  and correction of the legacy planning/execution boundary.

## Next release boundaries

| Priority | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 1 | Extend approved task runs to sandboxed build/test execution | Keep persisted approvals, isolation, leases and artifacts; execute only in a verified sandbox; capture build/test evidence and cancellation without host execution |
| 2 | Complete app-builder delivery | Idea → generated files → isolated build/test → working preview → reviewed export; failed builds expose actionable logs and never report ready |
| 3 | Automation and lead follow-up | Authorized source import → reviewed classification → configured trigger → queued action; bounded retries, idempotent external effects, opt-outs and audited outcomes |
| 4 | Commercial readiness | Measured tenant quotas, billing/webhook tests, recoverable failures and end-to-end subscription access; no new paid infrastructure without authorization |
| 5 | Remaining product surfaces | Audit Design Studio, Career Assistant, Arabic learning, Feed and Device Control individually; deliver one real user journey per surface before broadening |

For each increment: inspect current code, define testable criteria, implement the
complete UI/API/data path, test failure and authorization paths, then release only
the tested commit. These rows are planned work, not claims of delivered capability.

## Known release operations issue

The GitHub `RENDER_DEPLOY_HOOK_URL` secret targets another Render service. The
existing deploy guard correctly refuses it. The service serving Flow is
`srv-d6705koboq4c7384n0cg` in the user-confirmed Yassir workspace. Correct the secret
through GitHub's secret form; never paste its value in chat or source control.
Until corrected, a successful manual Render deployment must be verified by exact
commit and health checks; do not report the GitHub deploy job as successful.
