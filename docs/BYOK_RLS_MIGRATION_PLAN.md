# BYOK database isolation — inactive migration design

The existing global `app.tenancy.rls.enable_scoped_rls` deliberately allows
unscoped connections. **Do not add BYOK to that generic table list.**

Apply only after reviewing PostgreSQL roles, transaction pooling, schema
ownership, and testing with a non-superuser/non-BYPASSRLS app role:

1. Create `ai_user_credentials` using `app.ai.user_credentials.SCHEMA_SQL`.
2. Apply `app.ai.credential_rls.RLS_SQL` in the same reviewed migration.
3. Verify FORCE RLS is enforced for the actual application database role.
4. Require `scoped_credential_transaction` around every credential
   operation, passing IDs only from verified `OrgContext`.
5. Test missing scope, wrong org, wrong user, cross-org insert/update/delete,
   reused pooled connections, nested transactions and concurrent requests.
6. Do not expose API routes until encryption key rotation and redaction are
   implemented and verified.

Important: custom PostgreSQL GUC values are not authentication on their
own. An attacker able to execute arbitrary SQL as the app role can set
these variables. The scope is defense-in-depth, not a substitute for
parameterized SQL, verified identity and least-privilege database roles.

No schema or policy was applied to any database by this commit.
