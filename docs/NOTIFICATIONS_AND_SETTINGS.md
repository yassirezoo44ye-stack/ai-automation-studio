# Notifications and settings: functional journeys

## Fixes

- The notification bell lives in the top bar. Its popup is a body portal positioned
  within the viewport, choosing space above/below the trigger. Remove the old
  sidebar-only upward placement and conflicting mobile offsets. Opening the inbox
  refreshes saved notifications and preferences even if realtime is reconnecting.
- Notification preferences are a separate dialog portal. Mouse/keyboard interaction
  inside that dialog must not dismiss its parent popup. Escape closes the active
  dialog first. Preserve internal action destinations, including query strings and
  project routes; ignore invalid/external destinations. Switch to the notification's
  organization only when it is in the user's loaded membership list.
- Workflow notifications open the requested run's saved details and step results
  through the existing org-authorized endpoint, including completed/failed runs
  absent from the active list. A missing/forbidden run shows an error, not a
  placeholder or a newly launched workflow.
- asyncpg returns JSONB as text by default. Normalize notification actions to an
  object with string label/href, accepting an already decoded object too. Invalid
  actions become null. This applies both to saved inbox records and dispatched rows.
- Read/archive/delete updates follow successful server responses. Failed changes
  remain visible with retry feedback. Deletion uses the shared authenticated fetch
  so expired-session recovery works. Refresh responses predating a successful write
  cannot undo the confirmed local result. Keep owner scoping in every SQL mutation.
- Preferences load/save failures are visible. Disable editing until preferences
  load, serialize changes against confirmed state, and keep network calls outside
  React state updaters. Ignore stale reads and responses from a prior user session.
- Settings navigation/content adapt to narrow screens and keep the active tab in
  view. Sidebar mode restores on startup. The model selectors share validated
  browser preferences with general chat, Copilot, App Builder and Dev requests.
  Backends validate allowed model IDs and use the selection for inference and
  chat context budgeting. Custom agents retain their own configured model.
- The System tab reads full diagnostics, not the liveness response (which has no
  database/version fields). Browser storage failures do not display a saved claim.

Preferences for models, sidebar, appearance and language remain browser-local;
they are not synchronized across devices/accounts. Notification category
preferences are stored per authenticated user in PostgreSQL. Supported model
selection does not certify provider availability or change quotas/billing rules.

## Verification

- Actual REST router and NotificationService against PostgreSQL in isolated test
  schemas: JSON action round trip, read state, preferences, validation, deletion and
  cross-user mutation denial. Dedicated test DB URLs only; production data is not
  used. CI uses its dedicated STUDY_TEST_DATABASE_URL; local verification uses
  NOTIFICATION_TEST_DATABASE_URL.
- Frontend regression tests cover portals/nested settings, failed writes, stale
  responses, StrictMode, persisted model/sidebar settings and actual build request
  selection. Backend route tests capture the selected inference model in normal
  and streamed chat/build calls, rejecting unsupported models before inference.
- Browser verification uses the real app UI, REST routes and PostgreSQL service,
  with synthetic local authentication/bootstrap. AI responses are intercepted to
  verify request model selection without provider charges. Desktop and Arabic RTL
  mobile journeys cover visible popup geometry, saving/reloading preferences,
  controlled write failures, read/navigation, settings persistence and diagnostics.
  Realtime WebSocket transport is outside this browser fixture; its ticket and
  reconnect regression tests remain required. Never claim a live authenticated
  production journey from these local checks alone.
