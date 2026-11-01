# Flow platform action review — 2026-11-01

## Evidence and scope

The reproducible inventory scans all 162 production TSX files under `src/renderer`.
It records 604 JSX action sites: 361 native buttons, 151 `GoldButton` sites,
and 92 other clickable targets, form handlers or links. Mapped components can
render many controls at runtime; these are source-site counts.

Run `node scripts/audit-ui-actions.mjs docs/platform-actions-inventory.json` to
refresh the inventory. Each entry is explicitly `source-only`: a handler, submit
action or disabled guard is wiring evidence, not evidence that its operation
succeeded. No unbound native/GoldButton sites were found by this structural scan.

## Confirmed repairs

| Area | Fault | Result |
| --- | --- | --- |
| Automation | HTTP rejection of update/delete looked successful locally | Change the task only after server acceptance; preserve it and report rejection |
| Settings / API keys | Rejected revocation removed the key locally | Keep the key visible and show failure |
| AI assistant | Task update and agent delete ignored rejected HTTP responses | Check responses and surface failure |
| Developer workspace | Rejected clear erased the local file list; failed ZIP silently returned | Preserve files on rejection; report download/selection errors; clean up download URLs |
| Clipboard | Unsupported or rejected clipboard calls could throw, silently fail or show success too early | Confirm the modern or legacy copy result; clean up temporary DOM; restore focus; show failures |
| Clipboard consumers | Code blocks, chat, careers, leads, devices, settings, installation commands and social text had inconsistent behavior | Use the same confirmed-copy helper and report rejected writes |
| Training Studio | Actions swallowed errors; publish button retained stale course status | Surface action errors; reflect the server's published/draft status; prevent repeat publish while pending |
| Feed tabs | Explore/Following only changed tab styling | Explore navigates to Discover; Following is explicitly unavailable until implemented; For You resets filtering |
| Shared feed links | Shared item ID was ignored | Place the requested item first; fetch a missing shared creation through the existing permission-checked endpoint; explain an unavailable item |
| Business Lab | Nonexistent `joined_at` column and obsolete auth token broke plan actions | Reuse shared authenticated requests, active-membership lookup, readable errors, bounded input and guarded actions from the previously reviewed repair |

Business Lab changes incorporate the eight-file repair prepared in PR #33.
They preserve stream ticket authentication, scope stream reads, and do not bypass
organization permissions. Existing work outside this isolated branch was retained.

## Automated execution evidence

- Navigation tests click all 13 main sidebar destinations and verify active page/content agreement.
- Direct-route tests mount the routing shell for 29 destinations. Feature pages
  are mocked in these tests: they verify routing, not every feature's own actions.
- New regression tests cover denied API-key revocation, denied/successful task
  updates, denied task/agent deletion, clipboard completion/fallback/failure,
  workspace clear/download rejection, publish/unpublish, rejected course
  publishing, Explore/Following behavior, and direct/unavailable shared feed items.
- Existing library, authentication, billing, app-builder, devices/services, lead,
  SaaS, notification, and other tests run with the complete suite. A passing suite
  does not expand a test's actual coverage.
- The separate Business Lab database/auth/plan tests verify its backend repair.

Exact final command results and deployed commit are recorded in the pull request
and release response, rather than embedded in generated inventory entries.

## Source review by area

All rows below have source wiring evidence. Functional evidence varies by row.

| Area | Action sites | Additional evidence |
| --- | ---: | --- |
| Shared/layout | 46 | Full sidebar and direct-route tests; copy helper/component regressions |
| Home | 22 | Route and existing organization guards |
| New Project | 1 | Route and existing creation tests |
| AI assistant | 23 | Route, agent deletion and existing chat/services tests |
| Feed | 13 | Filtering, Explore, sharing-loader and existing interaction/service tests |
| Careers | 20 | Route and existing profile/draft/filter tests; shared copy helper |
| Leads | 21 | Route and existing lead/AI/follow-up tests; shared copy helper |
| Automation | 13 | Route and new task action regressions |
| Devices | 20 | Route, existing service tests, shared copy helper |
| Discover | 15 | Route and existing API/service tests |
| Study Library | 22 | Route and existing search/access/workflow/cancellation tests |
| Teams | 17 | Route and existing team/chat service tests |
| Billing | 12 | Route and existing billing tests; no live transaction |
| Settings | 12 | Route, API-key revocation and existing settings tests |
| Business Lab | 13 | Route, plan/action/client tests and backend regressions |
| App Builder | 40 | Route and existing creation/modify/export tests |
| Developer workspace | 26 | Route, clear/download rejection tests and copy helper |
| Design Studio | 72 | Route; canvas/export operation needs browser exercise |
| Training Studio | 58 | Route and new publish/unpublish/failure tests; action errors reviewed |
| SaaS Factory | 11 | Route and existing organization/pipeline tests |
| AgentOS | 13 | Route and existing job/agent backend tests; cancellation response reviewed |
| Runs | 6 | Route and existing run services/backend tests |
| Integrations | 11 | Route and existing integration tests; live provider auth not exercised |
| Marketplace | 13 | Route and source HTTP/error checks; no live install/purchase |
| Plugins | 9 | Route and source HTTP/error checks; no live install |
| Sandbox | 6 | Route and source stop/approve checks; no live worker permission change |
| AI Routing | 11 | Route and source action review; no live provider/budget change |
| Observability | 4 | Route and source refresh review |
| Organizations | 7 | Route and existing backend isolation tests; no live membership change |
| Social | 8 | Route, source actions and copy helper; no external publishing |
| Authentication | 17 | Existing auth/OAuth tests; no new account/credential changes |
| Landing | 22 | Source navigation and form wiring; no live checkout |

## Remaining live verification

The available cloud browser does not share the owner's signed-in session.
Private actions were not clicked in the owner's production data. A signed-in
test workspace is still needed to exercise every enabled action with its real
payload, verify the resulting stored state, and check mobile download behavior.

Payment, external social publishing, destructive production actions, device
control and external credential/permission changes were not used as smoke tests.
Disabled Comments/Following, Git integration and providers requiring setup are
availability limits, not completed implementations. They must remain visibly
unavailable rather than be reported as functioning actions.

The inventory and passing tests therefore support the repairs and coverage above;
they do not certify that every runtime action has completed in production.
