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
assets/pages/import/export, plugin management, team headers/cards, Home's project
and example controls, and AgentOS recommendations. Home/AI/new project/leads/
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
