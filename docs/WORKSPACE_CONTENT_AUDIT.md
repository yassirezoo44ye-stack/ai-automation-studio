# Flow workspace content policy and coverage

All workspace screens should put the current task, required inputs and result
first. Secondary context is collapsed under a descriptive heading. Avoid repeated
brand blocks, promotional copy, idle inventories, nonfunctional navigation,
parallel setup forms and generic KPI walls. Keep auth, organization/permissions,
costs, approval decisions, cancellation, errors and recovery visible where needed.
Numbers stay visible when measurement is the screen's actual job.

`WorkspaceDetails` loads optional content on first expansion. Closing it retains
mounted forms and their drafts, with `hidden` removing controls from focus and
accessibility navigation. It supports controlled expansion for workflow steps.
Do not put an approval or a required error behind this disclosure.

| Workspace | Primary content / reviewed treatment |
| --- | --- |
| Home | Request, five recent projects, actionable attention and running work only. |
| AI assistant | Conversation and composer; example prompts collapsed. |
| Agents / project plans | Agent configuration and saved plans/tasks/results retained. |
| App Builder | Copilot, review, runtime and result; inert section sidebar removed, share moved to top bar, export retained. |
| Dev | Source generation, files, build/run state and results are core; retained. |
| Design | Canvas and direct editing tools are core; prior compact actions retained. |
| SaaS Factory | Idea or active pipeline; repeated subtitle removed, examples collapsed. |
| Business Lab | Plan list/input/output; promotional empty-state copy and large icon removed. |
| Automate | Tasks, filters, workflows and approvals are core; retained. |
| AgentOS | Command/result; examples collapsed, promotional readiness badges removed. |
| Runs | Run table/filter/detail/cancel; summary tiles collapsed. |
| Leads | Search, pipeline and drafting; repeated hero copy removed, aggregate stats and follow-up setup collapsed. |
| Careers | Opportunities/results first; profile/import/Gmail setup collapsed and opened by workflow steps; aggregate counts collapsed. |
| Devices | Device list/status/enrolment; repeated subtitle removed, topology explanation collapsed. |
| Integrations | Search and connectable integrations; unavailable placeholders excluded, summary tiles collapsed. |
| Training | Opens course work directly; overview remains a destination with optional metrics; repeated subtitle removed. |
| Study library | Search, subjects, lessons/downloads; promotional hero removed, membership gates and recheck preserved. |
| Teams | Team/member management and conversations are the actual work; compact actions retained. |
| Organizations | Organization selection/creation; optional activity history collapsed. |
| Settings | Opens preferences directly; technical system/keys remain destinations, usage counts collapsed; system data requested only in its tab. |
| AI Routing | Provider/model/budget configuration is core; repeated subtitle removed. |
| Observability | Metrics, incidents, diagnostics are the work; metrics retained, repeated subtitle removed. |
| Billing | Subscription, prices, quotas, invoices and payment actions are the work; retained. |
| Plugins | Installed configuration, permissions and explicit installation are core; retained. |
| Sandbox | Workers and permission decisions are core; retained. |
| Social | Source input/output retained, long source description collapsed. |
| Marketplace | Search, listing, price/permissions retained; decorative card banners reduced. |
| Discover | Browse and manage creations; repeated subtitle removed. |
| Feed | Single content item and its actions are core; prior compact treatment retained. |
| Authentication | Security, identity and recovery flows retained. |
| Public landing | Public product explanation remains outside the authenticated workspace. |

The shared workspace top bar no longer repeats the Flow brand/breadcrumb prefix;
it retains organization context and the current destination. Direct routes and
command search remain available. This changes presentation, not backend execution,
tenant authorization, publication rules or billing behavior.

Verification must cover primary actions after simplification, draft preservation,
closed-section accessibility, expanding setup from a workflow step, export without
the removed App Builder sidebar, membership rechecks, and Arabic/mobile layouts.
