# BYOK production release gate (draft)

**Status:** not approved for production. PR #59 remains draft.

## Security invariants
- Credential reads, writes, verification and rotation run inside a transaction
  scoped to an authenticated organization and user.
- Database connections use a restricted, non-owner, non-BYPASSRLS role.
  RLS is defense-in-depth, not a substitute for authorization.
- `BYOK_FERNET_KEY` is mandatory; previous keys remain available for reads
  throughout migration. Secrets never appear in reports or logs.
- A rotation failure must roll back all changes for that user. Concurrent
  writes must not lose the latest value.

## Required before migration
1. Build an authenticated, authorized inventory of all tenant/user scopes
   without exposing ciphertext or API keys in logs.
2. Implement a durable per-scope checkpoint and retry strategy with explicit
   failure states. The existing helper does **not** provide this.
3. Audit the entire deployment with the primary-key-only verifier; a
   per-user `complete: true` result does not prove global completion.
4. Resolve every unreadable ciphertext and verify no previous-key ciphertext
   remains across all scopes. Check for concurrent writes during the audit.
5. Exercise backup, restore, rollback, interrupted migration and key-loss
   scenarios in a disposable environment.
6. Require security review, passing BYOK/PostgreSQL tests, CI and CodeQL,
   and explicit owner approval before merging or deploying.

## Do not
- Remove `BYOK_FERNET_PREVIOUS_KEYS` based on one user's audit.
- Invoke the migration helper from a public API or an untrusted DB connection.
- Run tests against production credentials or a production database.
- Interpret successful isolated tests as production readiness.
