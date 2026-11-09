# Main chat reliability: review boundary

This change extends the existing copilot/flow-conversation-reliability branch.
It preserves concurrent commit 44938bef62390b699ad041ba2c66953c6735ef44,
including its floating copilot history picker, states, and tests. It does not
replace those files with an earlier local implementation.

## Changes in this follow-up

- Wire the existing Python 32,000-character prompt contract into RunRequest.
- Default ChatTab accepts 32,000 Unicode code points and preserves original
  whitespace/code/newlines. Custom agent composer limits remain 4,000. The
  concurrent floating copilot still has its own 4,000-character limit; aligning
  that component is explicitly outstanding.
- Main chat draft clears only when the server acknowledges persistence via
  conv_id. No acknowledgment keeps the draft. No browser storage is introduced.
- The server yields conv_id before attempting AI bulkhead admission, so clients
  know the user message is saved even when generation is rejected for capacity.
- Main chat uses authenticated apiFetch, including existing expired-token handling.
- Shared SSE reader handles byte/record boundaries and CRLF, reports premature
  EOF, and cleans up the reader. Main chat uses it; the concurrent floating
  copilot parser is preserved and remains separate.
- Main chat history is tagged by conversation and disabled during streaming.
  Switching/deleting chats and changing project/agent are disabled during a
  stream. Stop remains available. Initial default-project load opens the latest
  conversation, not necessarily the exact previous selection/project.
- A synchronous in-flight ref prevents same-tick duplicate main-chat sends.

## Validation actually performed

Node 24: `node --experimental-strip-types --test tests/frontend/chat-reliability.node.mjs`
passes 7 tests: Unicode budgets, legacy limit, split UTF8/SSE, premature EOF,
terminal errors, malformed data, and reader cleanup.

The changed Python router parses successfully. Its actual RunRequest class was
isolated from the AST and validated with Pydantic: exact string preservation,
32,000 Unicode code points accepted, and 32,001 rejected. This is isolated model
validation, not route/database integration.

Full TypeScript, React/Vitest, backend integration, browser QA, CI and production
checks have NOT been run locally: repository dependencies are unavailable.
A dependency-free Node contract workflow is included. Existing frontend checks
must verify the main-chat changes and the preserved concurrent copilot work.

## Remaining acceptance work

- Server-side idempotency: local click guards do not prevent duplicates across
  tabs or after an ambiguous transport failure following a successful write.
- Atomic conversation/message/activity writes and durable partial assistant output.
- Main ChatTab React regression tests for restoration and streaming/history races.
- Align floating copilot input and request limit with the shared contract without
  losing its newly added history UI or message-state semantics.
- Exact active project/conversation restoration and account/org lifecycle tests.
- No claim of fixing tool execution: the default chat still has auto_tools=False.
- No table merge or migration between legacy and ai_* conversation schemas.

## Platform architecture sequence

Stabilize persistence and end-to-end checks first, then connect project ->
conversation -> task -> run -> evidence with explicit permissions. Keep the
original request, reference content and constraints distinct. Apply metallic
visual tokens/accessibility in a later bounded PR; a visual overhaul must not
hide broken persistence. No main update, database migration or deployment is
part of this change. Roll back this follow-up commit to preserve the earlier
branch work.
