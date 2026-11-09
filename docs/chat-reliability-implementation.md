# Chat reliability implementation notes

## Current branch scope

This branch starts with a lossless prompt-budget contract at
`app/core/chat/prompt_contract.py`. It measures the exact submitted string,
including whitespace, Unicode, code, and line endings; it never silently
trims or truncates. Over-budget prompts receive a recovery message recommending
an attachment or linked parts.

## Important integration gap

The existing chat HTTP model still has a separate 4,000-character Pydantic
limit (`app/routers/chat.py::RunRequest`) and the ChatTab currently trims and
clears its composer before the stream succeeds. The new contract is not yet
wired to those call sites, so it does not by itself change runtime behavior.
This gap must be resolved before claiming the long-prompt or draft-recovery
acceptance tests pass. Do not treat this groundwork as a completed chat fix.

The chat route also persists user messages before provider completion but does
not associate a stable client request key with that write. Retries can
therefore duplicate messages; server-side idempotency remains outstanding.

## Review / rollback

The change is additive and does not alter existing database rows, APIs, or
runtime behavior. Review the helper and its tests; rollback by reverting the
single commit on this branch. No production deployment or external action is
part of this change.
