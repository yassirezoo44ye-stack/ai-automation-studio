# BYOK re-encryption primitive — review required

The opt-in rotate_user_credentials helper runs only inside a caller-provided
scoped_credential_transaction. It locks and re-encrypts up to 100 rows for a
single authenticated organization/user pair. It returns counts only, never
secrets. The caller must own transaction commit/rollback and authentication.

This is **not** a complete migration runner:
- It has no global tenant enumeration, checkpoint or durable audit.
- Repeated calls with a limit can revisit already rotated rows.
- There is no proof that all rows in a deployment have been migrated.
- Previous keys MUST remain configured until a separate complete verification.
- Do not schedule or expose this primitive through public API endpoints yet.
- Keep production credentials and databases untouched until reviewed.
