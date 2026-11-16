# BYOK security gates — before API activation

Status: branch-only, inactive. This is not an authorization or penetration-test
certificate.

## Verified in source review
- Existing `OrgContext` comes from authenticated organization membership.
- Current provider registry reads server environment credentials.
- Existing Fernet helper derives keys from `SESSION_SECRET`.

## Implemented
- Pure compute selection with no platform fallback.
- Prototype encrypted vault with org/user/provider-qualified SQL.
- Verified-context scope helper, private-to-owner even for org admins.
- Secret-free credential existence query.

## Blocking items before enabling routes or schema
1. Run unit tests in a clean environment and review failures.
2. Confirm the table's ownership model and add database-level RLS,
   FORCE ROW LEVEL SECURITY, and transactional verified identity context,
   or an equivalent proven isolation mechanism. The existing SCHEMA_SQL
   is **not** a production migration.
3. Replace SESSION_SECRET-derived encryption with a dedicated, rotated
   credential-encryption key and document recovery/rotation.
4. Add audit records, throttling, CSRF protections as applicable, and
   credential revocation propagation.
5. Ensure no request, error, trace, crash report, or log exposes API keys.
6. Make scoped provider calls avoid global provider objects and shared
   circuit-breaker/caching state across tenants.
7. Test authorization using two users in two organizations and real
   PostgreSQL transactions, including concurrent requests.
8. Confirm no preview deployments are publicly reachable and that
   no preview environment has production secrets or database access.

Do not merge, deploy, register routes, or initialize the table before
all blocking gates are verified and explicit owner approval is received.
