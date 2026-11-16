# BYOK RLS security boundary

The PostgreSQL row-level security policy requires both organization and user
identifiers and is tested against a restricted role without BYPASSRLS.
The context variables app.byok_org_id and app.byok_user_id are PostgreSQL
custom GUCs and can be set by any session with arbitrary SQL execution.
Therefore RLS here is defense-in-depth, **not** a protection against SQL
injection, compromised DB credentials, or untrusted raw SQL.

Production requirements before enabling endpoints:
- Authenticate and verify organization membership on each request.
- Never accept org_id or user_id from client payloads for vault access.
- Use parameterized queries and prohibit user-controlled SQL execution.
- Use a dedicated non-owner, non-superuser, non-BYPASSRLS database role.
- Set scope using transaction-local settings and verify no pool leakage.
- Do not return plaintext keys, ciphertext, or key values in logs/errors.
- Deploy schema and RLS in a reviewed migration, not at application startup.
- Test rollback, key revocation, encryption rotation, and tenant isolation.
- Do not enable BYOK or paid-provider fallback before review and approval.
