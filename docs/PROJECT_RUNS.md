# Durable approved task runs

In AI → Projects & plans, open a saved plan, select a task and execution mode,
review the scope, and explicitly approve the run. History, results and logs are
stored in PostgreSQL, independent of browser sessions or Redis availability.

## Supported execution modes

| Mode | Actual behavior | Boundaries |
| --- | --- | --- |
| Skill deliverable | Runs one of the nine shipped Flow skill agents through AgentKernel/InferenceEngine and saves the text output | Model usage may be billed; no execution tools, workspace reads or external actions |
| Read-only project inspection | Runs the built-in `inspect_project` agent against the verified owner's project workspace | Bounded source counts and manifest metadata; no source contents/secrets in output, no code/build/test execution, no network, no symlink traversal |

Caller-supplied agent names, shell commands, paths and tool lists are not execution
inputs. The server snapshots the immutable saved task, goal and verified project,
stores the approval time/hash, and forces an allowlisted agent. A completed run
means an output was produced, not that the task's acceptance criteria were met.
The task remains in progress until the user reviews and marks it done.

## Persistence, dispatch and recovery

`project_task_runs` is created by the existing startup schema path after plan/task
tables. Submission is transactional and serialized per user and parent plan.
Retries of the same caller/request UUID return the same run. Changed context or
runner under that UUID is rejected. Prerequisites must be done. At most three
queued/running runs per user and one per task are allowed.

A worker in the API process polls PostgreSQL every two seconds, with two active
runs per process. `FOR UPDATE SKIP LOCKED` prevents duplicate claims across
replicas; each claim receives a lease token and a 150-second lease. Dispatch
rechecks project ownership, task/prerequisite state and organization membership.
It passes only verified user/org/project context to the forced agent.

- Queued work survives a process restart and can be claimed by a new worker.
- Running work has a bounded execution window (approximately 120 seconds plus
  bounded database operations). Graceful shutdown interrupts active work.
- Expired leases become **interrupted**, never automatically requeued. Inspect
  the result/history before explicitly approving a new request UUID.
- Cancellation is idempotent for cancelled runs. Queued cancellation prevents
  invocation; running cancellation stops awaiting execution and discards late
  results. Already-started model usage may still be billed. Read-only filesystem
  work in a thread is bounded and can finish after cancellation; it has no writes.
- Finalization updates only a matching running lease. Cancellation, interruption
  or deletion cannot be overwritten by a late completion.
- Manual task edit/status/delete is blocked while a linked run is active.
  Cancellation/termination frees the task for user review and further edits.
- Output is bounded to 40,000 characters (a truncation notice is included when
  needed), stored as text, and downloaded as a private plain-text attachment.
  No HTML or generated code is executed by viewing/downloading the result.

Each request to list/read/cancel/download checks the plan's verified user and exact
organization scope. Run records cascade when the user/plan is deleted. History
returns active runs first and up to 50 recent records; details/artifacts are fetched
only on selection. Organization membership is checked before dispatch and whenever
the caller accesses the result; already-started work can finish after revocation.

## API

| Method | Path |
| --- | --- |
| POST | `/api/project-plans/{plan_id}/tasks/{key}/runs` |
| GET | `/api/project-plans/{plan_id}/runs` |
| GET | `/api/project-plans/{plan_id}/runs/{run_id}` |
| DELETE | `/api/project-plans/{plan_id}/runs/{run_id}` |
| GET | `/api/project-plans/{plan_id}/runs/{run_id}/artifact` |

Start body: `request_id` (UUID), `approved: true`, `runner` (`skill` or
`inspect_project`), and `skill_id` only for skill mode. Identity, organization and
snapshot are resolved server-side. No bearer tokens or provider credentials are
stored with the run. Run states are queued/running/completed/failed/cancelled/
interrupted, separate from pending/in_progress/done task progress.

`/health/deep` includes the noncritical `project_plan_runs` worker probe. A failed
poll is reflected by that probe; database availability remains a critical probe.
No new paid infrastructure is required. Redis-based jobs and other platform
execution routes retain their own behavior.

## Verification

Real PostgreSQL tests cover concurrent replay/capacity, claim exclusivity,
dependency and active-run guards, scope isolation, artifact authorization,
queued/running cancellation, stale leases, graceful shutdown, dispatch context and
concurrent manual completion. Inspector tests cover project ownership and symlink,
secret and code-execution boundaries. Frontend tests cover scope-bound approval,
retry keys, restored results and cancellation.

Chromium verification used the real API, PostgreSQL, worker, AgentKernel and
filesystem inspector with a loopback-only test identity. Only initial plan drafting
used a deterministic model fixture. It exercised approval → dispatch → stored
result → download → reload → restored result → manual acceptance, and verified
that the project's executable test payload never ran. Live paid model calls and
production-account behavior are not established by that test.

The next execution expansion is a separately authorized sandboxed build/test
adapter with persisted execution evidence, not arbitrary host subprocess access.
