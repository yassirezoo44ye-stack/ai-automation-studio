# Session and execution recovery

Protected chat, Copilot, Dev generation and App Builder use the shared authenticated
transport. A server-declared `token_expired` 401 permits exactly one refresh and
retry. Ordinary 401s and authentication endpoints do not trigger this recovery.
Captured `authH()` headers rotate with the token; standard Headers and tuple lists
are supported. A retry preserves the original organization and body, respects
cancellation, and is suppressed after logout/account changes or for explicitly
supplied credentials belonging to another identity.

The shared JSON SSE reader handles UTF-8 byte boundaries, CRLF, multiline data,
and the last frame without a trailing newline. Consumers require an explicit
terminal event; EOF alone is not success. Reader cancellation releases connections.
Disconnected generation is never automatically repeated: partial replies, source
files and console logs remain available with an error instead of a success state.

Dev Run waits for successful JSON confirmation from project sync before requesting
execution. Failed source synchronization leaves a visible error and cannot start
execution against older files. Aborting also cancels the sync request.

Custom-agent replies and message counters commit in one PostgreSQL transaction
before `done` is sent. A write or commit failure produces an error, never `done`.
A client may disconnect immediately at `done` without losing the saved reply.
Conversation deletion and task updates in the shared chat service reject server
failures rather than silently allowing a success state.

## Verification

- API transport tests cover token rotation, stale headers, cancellation, original
  organization/payload preservation, account changes and foreign credentials.
- Protocol tests cover split Arabic bytes, CRLF, final completion and reader cleanup.
- Run UI tests cover rejected sync, disconnected execution and confirmed exit.
- Copilot and App Builder tests cover partial output and terminal frames.
- Agent integration tests use isolated real PostgreSQL schemas, immediate client
  disconnect and failures during both statement execution and transaction commit.
- Local Chromium exercised the actual Run component in Arabic at a mobile viewport:
  HTTP failure blocks run, an expired session retries, final completion renders,
  and disconnection preserves logs. HTTP responses were deliberately controlled;
  no production user data or paid AI calls were used.

## Boundaries

These checks verify the listed execution paths, not every Flow workspace or every
possible generated application. They do not turn local files into a deployment,
add payment/email credentials, or make client-side abort a guarantee that a remote
process stopped. Production database schemas require no migration for this change.
