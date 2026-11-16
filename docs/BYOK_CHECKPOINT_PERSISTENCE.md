# BYOK checkpoint persistence design (not deployed)

The SQL draft in `db/byok_rotation_checkpoints.sql` stores one checkpoint
per `(org_id, user_id)`, with status, attempt, lease token, expiry, and a
non-secret error code. No credential values or ciphertext are stored here.

## Execution contract (not implemented)
1. Obtain an authenticated, authorized, complete scope inventory.
2. Claim each scope using an atomic conditional UPDATE that assigns a new
   random lease token and expiry. Do not treat `running` as immediately
   retryable; reclaim only expired leases under a transaction.
3. Re-encrypt and verify under the scoped credential transaction.
4. Mark verified only if the lease token still matches and the verification
   is successful; mark failures without writing plaintext errors.
5. Retry after an interruption only when the old lease has expired.
6. Reconcile new/deleted scopes and concurrent credential changes before
   interpreting a deployment-wide audit as complete.

The current in-memory planner is a *candidate selector only* and cannot
prevent simultaneous workers from selecting the same scope. This draft does
not implement an inventory source, lease-claim worker, or global audit
snapshot. It is not permission to remove previous encryption keys.
