# Essential actions in Flow

Keep the current screen's creation, save/send/run action visible. Keep stop,
explicit approval, rejection and cancel visible when work needs them. Keep form
submission and recovery actions visible; never hide authorization requirements.
Move export, sharing, administrative edits and destructive management into More.
Tabs with different workspaces remain navigation, rather than being hidden as
secondary actions. Use a select for long, mutually exclusive filter lists.

The shared SecondaryActions disclosure retains original handlers, disabled
states and confirmations. Its content is explicitly hidden while closed, opens
with keyboard activation, closes with Escape (restoring focus) or an outside
pointer, and expands in normal flow so scroll containers cannot clip a floating
menu. Arabic/English labels and logical-direction layout are supported.

Applied to agent cards, conversation tools, App Builder sidebar, Design Studio
assets/pages/import/export, plugin management, team headers/cards and AgentOS recommendations. Home/AI/new project/leads/
automation/settings stay in the global sidebar; the seven specialist destinations
are in More, automatically expanded for their active page. Direct routes and
command search retain all destinations. Careers uses one status filter instead
of seven buttons. The unavailable Feed comment control and redundant AI header
agent button were removed; the actual agent creation form remains in Agents.

Screens already showing a single main action or a save/cancel pair retain those
controls (including plans/runs, approvals, devices, billing, organizations,
integrations, observability, training, study, business plans and authentication).
Editing tools such as undo/redo and zoom retain their direct controls. This is a
presentation change and does not add execution rights or alter backend behavior.

Validation: regression tests cover every sidebar destination including direct
routes; disclosure tests cover visibility, disabled state, callbacks, Escape and
outside clicks. Retain these checks when moving more actions into disclosures.

## Work-focused Home

Home shows one assistant request and at most five recent projects. A link opens
all projects. Attention appears only for actual failed runs, approvals, security
reviews or unavailable checks; running workflows appear only when running, capped
at three with access to the full workspace. No integration/use-case catalogues,
agent inventory, KPI wall, activity feed, duplicate build prompt or quick-launch
panels are rendered. Agent and lead inventory requests were removed from Home.
Organization changes remount the scoped view so old work cannot flash in the new
organization. Backend features remain accessible in their own workspaces.
