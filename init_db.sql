-- =============================================================================
-- Axon Automation Studio — core database bootstrap
-- =============================================================================
--
-- Creates the `axon` schema: tenants, users, memberships, RBAC (roles + scopes),
-- API keys, encrypted integration credentials, webhook endpoints with replay
-- protection, and an append-only audit log.
--
-- Security model
-- --------------
-- * Every tenant-owned table has ROW LEVEL SECURITY enabled AND forced, so the
--   policies apply even to the table owner.
-- * Policies are FAIL-CLOSED: when `app.current_tenant_id` is unset, a query
--   sees zero rows and every write is rejected. There is no "unscoped means
--   everything" escape hatch.
-- * The application runtime switches to the NOLOGIN role `axon_app` inside
--   each transaction (`SET LOCAL ROLE axon_app`, done by app/core/db.py).
--   `axon_app` has NOBYPASSRLS, so even a superuser login is held to the
--   policies once it has switched role.
-- * Scopes are enforced twice: by the API layer, and again here through
--   `axon.has_scope()` inside the write policies. A member can never grant a
--   role, role scope or API key carrying a scope they do not hold themselves.
-- * Secrets are never stored in plaintext. Integration tokens and webhook
--   secrets must be Axon ciphertext envelopes (`axv1.<key-id>.<payload>`,
--   produced by app/core/config.py's TokenCipher); API keys are stored only
--   as an HMAC-SHA256 digest.
-- * Pre-authentication lookups (login by email, API key by prefix) go through
--   narrow SECURITY DEFINER functions instead of opening the tables.
--
-- Requirements: PostgreSQL 15+ (UNIQUE NULLS NOT DISTINCT).
-- Idempotent: safe to run repeatedly. Run it as the schema owner (the role
-- that owns the database or a role with CREATE on it). Creating the
-- `axon_app` role needs CREATEROLE; without it the script stops with the
-- exact statements a DBA has to run first.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS axon;
COMMENT ON SCHEMA axon IS 'Axon Automation Studio core: tenancy, RBAC, secrets, audit.';

-- -----------------------------------------------------------------------------
-- Runtime role
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'axon_app') THEN
        BEGIN
            CREATE ROLE axon_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE EXCEPTION 'axon: cannot create role axon_app (needs CREATEROLE). Ask a DBA to run: CREATE ROLE axon_app NOLOGIN NOBYPASSRLS; GRANT axon_app TO <runtime login>; then re-run this script.';
        END;
    END IF;
END
$$;

-- Let the login running this script switch into axon_app (the runtime does
-- SET LOCAL ROLE axon_app). Harmless for a superuser.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'axon_app')
       AND NOT pg_has_role(current_user, 'axon_app', 'MEMBER') THEN
        EXECUTE format('GRANT axon_app TO %I', current_user);
    END IF;
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'axon: could not grant axon_app to %, grant it manually', current_user;
END
$$;

-- -----------------------------------------------------------------------------
-- Session context helpers
-- -----------------------------------------------------------------------------
-- The GUCs are set per transaction by app/core/db.py with
-- set_config(..., is_local => true), so they can never leak to the next
-- borrower of a pooled connection. A connection that once had a local GUC
-- reports '' (not NULL) afterwards, hence the nullif().

CREATE OR REPLACE FUNCTION axon.current_tenant_id() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE
    SET search_path = pg_catalog
AS $$
    SELECT nullif(current_setting('app.current_tenant_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION axon.current_user_id() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE
    SET search_path = pg_catalog
AS $$
    SELECT nullif(current_setting('app.current_user_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION axon.current_scopes() RETURNS text[]
    LANGUAGE sql STABLE PARALLEL SAFE
    SET search_path = pg_catalog
AS $$
    SELECT coalesce(
        string_to_array(nullif(current_setting('app.current_scopes', true), ''), ' '),
        ARRAY[]::text[]
    )
$$;

-- True when the session holds `required`, either exactly, through the global
-- wildcard '*', or through a resource wildcard such as 'workflows:*'.
CREATE OR REPLACE FUNCTION axon.scope_covers(held text[], required text) RETURNS boolean
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path = pg_catalog
AS $$
    SELECT required = ANY (held)
        OR '*' = ANY (held)
        OR (split_part(required, ':', 1) || ':*') = ANY (held)
$$;

CREATE OR REPLACE FUNCTION axon.has_scope(required text) RETURNS boolean
    LANGUAGE sql STABLE PARALLEL SAFE
    SET search_path = pg_catalog
AS $$
    SELECT axon.scope_covers(axon.current_scopes(), required)
$$;

-- Raises unless every scope in `granted` is covered by the caller's scopes.
-- Only enforced inside a tenant context: provisioning code running without a
-- tenant (system bootstrap) is trusted and is not subject to it.
CREATE OR REPLACE FUNCTION axon.assert_can_grant(granted text[]) RETURNS void
    LANGUAGE plpgsql STABLE
    SET search_path = pg_catalog
AS $$
DECLARE
    s text;
BEGIN
    IF axon.current_tenant_id() IS NULL THEN
        RETURN;
    END IF;
    FOREACH s IN ARRAY coalesce(granted, ARRAY[]::text[]) LOOP
        IF NOT axon.has_scope(s) THEN
            RAISE EXCEPTION 'axon: cannot grant scope "%" that the caller does not hold', s
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION axon.touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END
$$;

-- -----------------------------------------------------------------------------
-- Tenants
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.tenants (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text        NOT NULL UNIQUE
                            CHECK (slug ~ '^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$'),
    name        text        NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    plan        text        NOT NULL DEFAULT 'free'
                            CHECK (plan IN ('free', 'starter', 'pro', 'team', 'enterprise')),
    status      text        NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'deleted')),
    settings    jsonb       NOT NULL DEFAULT '{}'::jsonb
                            CHECK (jsonb_typeof(settings) = 'object'),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz
);

-- -----------------------------------------------------------------------------
-- Users (global identities; tenant access comes from memberships)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.users (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    email              text        NOT NULL
                                   CHECK (email = lower(btrim(email)))
                                   CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$')
                                   CHECK (length(email) <= 320),
    display_name       text        CHECK (display_name IS NULL OR length(display_name) <= 120),
    password_hash      text,
    is_active          boolean     NOT NULL DEFAULT true,
    email_verified_at  timestamptz,
    mfa_enabled        boolean     NOT NULL DEFAULT false,
    last_login_at      timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON axon.users (email);

-- -----------------------------------------------------------------------------
-- RBAC: scope catalog, roles, role → scope grants
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.scopes (
    code         text PRIMARY KEY CHECK (code ~ '^[a-z][a-z_]*:(?:[a-z][a-z_]*|\*)$'),
    description  text NOT NULL
);

-- tenant_id NULL = built-in system role shared by every tenant (read-only).
CREATE TABLE IF NOT EXISTS axon.roles (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid        REFERENCES axon.tenants (id) ON DELETE CASCADE,
    key          text        NOT NULL CHECK (key ~ '^[a-z][a-z0-9_]{1,39}$'),
    name         text        NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
    description  text,
    is_system    boolean     NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT roles_tenant_key_key UNIQUE NULLS NOT DISTINCT (tenant_id, key),
    CONSTRAINT roles_system_has_no_tenant CHECK (is_system = (tenant_id IS NULL))
);
CREATE INDEX IF NOT EXISTS roles_tenant_idx ON axon.roles (tenant_id);

CREATE TABLE IF NOT EXISTS axon.role_scopes (
    role_id     uuid NOT NULL REFERENCES axon.roles (id) ON DELETE CASCADE,
    scope_code  text NOT NULL REFERENCES axon.scopes (code) ON DELETE CASCADE,
    PRIMARY KEY (role_id, scope_code)
);

-- -----------------------------------------------------------------------------
-- Memberships
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.memberships (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid        NOT NULL REFERENCES axon.tenants (id) ON DELETE CASCADE,
    user_id     uuid        NOT NULL REFERENCES axon.users (id) ON DELETE CASCADE,
    role_id     uuid        NOT NULL REFERENCES axon.roles (id) ON DELETE RESTRICT,
    status      text        NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'invited', 'suspended')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT memberships_tenant_user_key UNIQUE (tenant_id, user_id)
);
CREATE INDEX IF NOT EXISTS memberships_user_idx ON axon.memberships (user_id);
CREATE INDEX IF NOT EXISTS memberships_role_idx ON axon.memberships (role_id);

-- -----------------------------------------------------------------------------
-- API keys (only an HMAC digest of the secret is stored)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.api_keys (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid        NOT NULL REFERENCES axon.tenants (id) ON DELETE CASCADE,
    created_by    uuid        REFERENCES axon.users (id) ON DELETE SET NULL,
    name          text        NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
    key_prefix    text        NOT NULL UNIQUE CHECK (key_prefix ~ '^axk_[A-Za-z0-9]{8,16}$'),
    key_hash      bytea       NOT NULL CHECK (octet_length(key_hash) = 32),
    scopes        text[]      NOT NULL DEFAULT ARRAY[]::text[]
                              CHECK (array_position(scopes, NULL) IS NULL),
    expires_at    timestamptz,
    last_used_at  timestamptz,
    revoked_at    timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS api_keys_tenant_idx ON axon.api_keys (tenant_id);

-- -----------------------------------------------------------------------------
-- Integration credentials (OAuth tokens, provider API keys) — ciphertext only
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.integration_credentials (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid        NOT NULL REFERENCES axon.tenants (id) ON DELETE CASCADE,
    provider        text        NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_]{1,39}$'),
    account_label   text        NOT NULL DEFAULT 'default'
                                CHECK (length(btrim(account_label)) BETWEEN 1 AND 120),
    ciphertext      text        NOT NULL
                                CHECK (ciphertext ~ '^axv1\.[A-Za-z0-9_-]{1,32}\.[A-Za-z0-9_-]+$'),
    key_id          text        NOT NULL CHECK (key_id ~ '^[A-Za-z0-9_-]{1,32}$'),
    granted_scopes  text[]      NOT NULL DEFAULT ARRAY[]::text[],
    expires_at      timestamptz,
    created_by      uuid        REFERENCES axon.users (id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT integration_credentials_key_matches
        CHECK (split_part(ciphertext, '.', 2) = key_id),
    CONSTRAINT integration_credentials_account_key UNIQUE (tenant_id, provider, account_label)
);
CREATE INDEX IF NOT EXISTS integration_credentials_key_idx ON axon.integration_credentials (key_id);

-- -----------------------------------------------------------------------------
-- Inbound webhooks: per-endpoint encrypted signing secret + replay ledger
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.webhook_endpoints (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid        NOT NULL REFERENCES axon.tenants (id) ON DELETE CASCADE,
    name               text        NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
    secret_ciphertext  text        NOT NULL
                                   CHECK (secret_ciphertext ~ '^axv1\.[A-Za-z0-9_-]{1,32}\.[A-Za-z0-9_-]+$'),
    tolerance_seconds  integer     NOT NULL DEFAULT 300 CHECK (tolerance_seconds BETWEEN 30 AND 900),
    is_active          boolean     NOT NULL DEFAULT true,
    created_by         uuid        REFERENCES axon.users (id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT webhook_endpoints_id_tenant_key UNIQUE (id, tenant_id)
);
CREATE INDEX IF NOT EXISTS webhook_endpoints_tenant_idx ON axon.webhook_endpoints (tenant_id);

-- A delivery id may be accepted once per endpoint: the primary key turns a
-- replayed request into a unique violation the handler maps to 409.
CREATE TABLE IF NOT EXISTS axon.webhook_deliveries (
    endpoint_id  uuid        NOT NULL,
    tenant_id    uuid        NOT NULL,
    delivery_id  text        NOT NULL CHECK (length(delivery_id) BETWEEN 8 AND 128),
    received_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (endpoint_id, delivery_id),
    FOREIGN KEY (endpoint_id, tenant_id)
        REFERENCES axon.webhook_endpoints (id, tenant_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS webhook_deliveries_received_idx ON axon.webhook_deliveries (received_at);

-- -----------------------------------------------------------------------------
-- Audit log (append-only)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.audit_events (
    id                bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id         uuid        NOT NULL REFERENCES axon.tenants (id) ON DELETE CASCADE,
    actor_user_id     uuid,
    actor_api_key_id  uuid,
    action            text        NOT NULL CHECK (action ~ '^[a-z][a-z0-9_.:-]{2,99}$'),
    resource_type     text,
    resource_id       text,
    ip_address        inet,
    user_agent        text        CHECK (user_agent IS NULL OR length(user_agent) <= 512),
    metadata          jsonb       NOT NULL DEFAULT '{}'::jsonb
                                  CHECK (jsonb_typeof(metadata) = 'object'),
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_events_tenant_time_idx ON axon.audit_events (tenant_id, created_at DESC);

CREATE OR REPLACE FUNCTION axon.forbid_audit_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
BEGIN
    -- Tenant deletion cascades are the only permitted removal path.
    IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM axon.tenants t WHERE t.id = OLD.tenant_id) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'axon: audit_events is append-only (% rejected)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$$;

-- -----------------------------------------------------------------------------
-- Integrity triggers
-- -----------------------------------------------------------------------------

-- Memberships: role must be a system role or belong to the same tenant; the
-- caller cannot hand out a role carrying scopes they do not hold; a tenant can
-- never lose its last active owner.
CREATE OR REPLACE FUNCTION axon.guard_membership() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
DECLARE
    role_tenant  uuid;
    role_scopes  text[];
    owner_role   uuid;
    owners_left  integer;
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT r.tenant_id INTO role_tenant FROM axon.roles r WHERE r.id = NEW.role_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'axon: unknown role %', NEW.role_id USING ERRCODE = 'foreign_key_violation';
        END IF;
        IF role_tenant IS NOT NULL AND role_tenant <> NEW.tenant_id THEN
            RAISE EXCEPTION 'axon: role belongs to another tenant' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF TG_OP = 'INSERT' OR NEW.role_id IS DISTINCT FROM OLD.role_id THEN
            SELECT coalesce(array_agg(rs.scope_code), ARRAY[]::text[]) INTO role_scopes
              FROM axon.role_scopes rs WHERE rs.role_id = NEW.role_id;
            PERFORM axon.assert_can_grant(role_scopes);
        END IF;
        IF TG_OP = 'UPDATE' AND NEW.tenant_id <> OLD.tenant_id THEN
            RAISE EXCEPTION 'axon: membership cannot move between tenants' USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;

    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT r.id INTO owner_role FROM axon.roles r WHERE r.tenant_id IS NULL AND r.key = 'owner';
        IF OLD.role_id = owner_role AND OLD.status = 'active'
           AND (TG_OP = 'DELETE' OR NEW.role_id <> owner_role OR NEW.status <> 'active')
           AND EXISTS (SELECT 1 FROM axon.tenants t WHERE t.id = OLD.tenant_id) THEN
            SELECT count(*) INTO owners_left
              FROM axon.memberships m
             WHERE m.tenant_id = OLD.tenant_id AND m.role_id = owner_role
               AND m.status = 'active' AND m.id <> OLD.id;
            IF owners_left = 0 THEN
                RAISE EXCEPTION 'axon: a tenant must keep at least one active owner'
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION axon.guard_role_scope() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
BEGIN
    PERFORM axon.assert_can_grant(ARRAY[NEW.scope_code]);
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION axon.guard_api_key() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
DECLARE
    unknown text;
BEGIN
    SELECT s INTO unknown
      FROM unnest(NEW.scopes) AS s
     WHERE NOT EXISTS (SELECT 1 FROM axon.scopes c WHERE c.code = s)
       AND s <> '*'
       AND NOT (s ~ '^[a-z][a-z_]*:\*$')
     LIMIT 1;
    IF unknown IS NOT NULL THEN
        RAISE EXCEPTION 'axon: unknown scope "%"', unknown USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'INSERT' OR NEW.scopes IS DISTINCT FROM OLD.scopes THEN
        PERFORM axon.assert_can_grant(NEW.scopes);
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.key_hash <> OLD.key_hash OR NEW.key_prefix <> OLD.key_prefix
                             OR NEW.tenant_id <> OLD.tenant_id) THEN
        RAISE EXCEPTION 'axon: api key material and tenant are immutable; issue a new key'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['tenants', 'users', 'roles', 'memberships',
                             'integration_credentials', 'webhook_endpoints'] LOOP
        EXECUTE format(
            'CREATE OR REPLACE TRIGGER %I BEFORE UPDATE ON axon.%I '
            'FOR EACH ROW EXECUTE FUNCTION axon.touch_updated_at()',
            t || '_touch_updated_at', t);
    END LOOP;
END
$$;

CREATE OR REPLACE TRIGGER memberships_guard
    BEFORE INSERT OR UPDATE OR DELETE ON axon.memberships
    FOR EACH ROW EXECUTE FUNCTION axon.guard_membership();

CREATE OR REPLACE TRIGGER role_scopes_guard
    BEFORE INSERT OR UPDATE ON axon.role_scopes
    FOR EACH ROW EXECUTE FUNCTION axon.guard_role_scope();

CREATE OR REPLACE TRIGGER api_keys_guard
    BEFORE INSERT OR UPDATE ON axon.api_keys
    FOR EACH ROW EXECUTE FUNCTION axon.guard_api_key();

CREATE OR REPLACE TRIGGER audit_events_append_only
    BEFORE UPDATE OR DELETE ON axon.audit_events
    FOR EACH ROW EXECUTE FUNCTION axon.forbid_audit_mutation();

-- -----------------------------------------------------------------------------
-- Seed: scope catalog and built-in roles
-- -----------------------------------------------------------------------------
INSERT INTO axon.scopes (code, description) VALUES
    ('tenant:read',          'View workspace settings'),
    ('tenant:manage',        'Change workspace settings and plan'),
    ('members:read',         'List members'),
    ('members:manage',       'Invite, remove and change roles of members'),
    ('roles:manage',         'Create and edit custom roles'),
    ('api_keys:manage',      'Create and revoke API keys'),
    ('integrations:read',    'See connected integrations and use their tokens'),
    ('integrations:manage',  'Connect, rotate and disconnect integrations'),
    ('webhooks:manage',      'Create and rotate inbound webhooks'),
    ('workflows:read',       'View automations'),
    ('workflows:write',      'Create and edit automations'),
    ('workflows:execute',    'Run automations'),
    ('agents:read',          'View AI agents'),
    ('agents:write',         'Create and edit AI agents'),
    ('agents:execute',       'Run AI agents'),
    ('billing:read',         'View usage, cost and invoices'),
    ('billing:manage',       'Change billing details'),
    ('audit:read',           'Read the audit log')
ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description;

INSERT INTO axon.roles (tenant_id, key, name, description, is_system) VALUES
    (NULL, 'owner',     'Owner',     'Full control of the workspace',                  true),
    (NULL, 'admin',     'Admin',     'Manage members, integrations and automations',   true),
    (NULL, 'developer', 'Developer', 'Build and run automations and agents',           true),
    (NULL, 'operator',  'Operator',  'Run existing automations and agents',            true),
    (NULL, 'viewer',    'Viewer',    'Read-only access',                               true)
ON CONFLICT ON CONSTRAINT roles_tenant_key_key DO UPDATE
    SET name = EXCLUDED.name, description = EXCLUDED.description;

INSERT INTO axon.role_scopes (role_id, scope_code)
SELECT r.id, s.code
  FROM axon.roles r
  JOIN axon.scopes s ON (
        r.key = 'owner'
     OR (r.key = 'admin'     AND s.code NOT IN ('tenant:manage', 'billing:manage'))
     OR (r.key = 'developer' AND s.code IN ('tenant:read', 'members:read', 'integrations:read',
                                            'workflows:read', 'workflows:write', 'workflows:execute',
                                            'agents:read', 'agents:write', 'agents:execute'))
     OR (r.key = 'operator'  AND s.code IN ('tenant:read', 'members:read', 'integrations:read',
                                            'workflows:read', 'workflows:execute',
                                            'agents:read', 'agents:execute'))
     OR (r.key = 'viewer'    AND s.code IN ('tenant:read', 'members:read',
                                            'workflows:read', 'agents:read'))
  )
 WHERE r.tenant_id IS NULL
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- Pre-authentication and provisioning functions (SECURITY DEFINER)
-- -----------------------------------------------------------------------------
-- Each one returns the minimum needed for its job and pins search_path so a
-- caller cannot hijack name resolution. They run as the schema owner, whose
-- only policy (owner_maintenance) requires the tenant GUC to be unset, so
-- each one clears it for its own work and restores the caller's value. GUC
-- changes are transactional, so an error also restores it.

CREATE OR REPLACE FUNCTION axon.find_login_user(p_email text)
    RETURNS TABLE (user_id uuid, password_hash text, is_active boolean, mfa_enabled boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    prev text := current_setting('app.current_tenant_id', true);
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    RETURN QUERY
        SELECT u.id, u.password_hash, u.is_active, u.mfa_enabled
          FROM axon.users u
         WHERE u.email = lower(btrim(p_email));
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
END
$$;

CREATE OR REPLACE FUNCTION axon.user_tenants(p_user_id uuid)
    RETURNS TABLE (tenant_id uuid, tenant_slug text, tenant_name text, role_key text, scopes text[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    prev text := current_setting('app.current_tenant_id', true);
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    RETURN QUERY
        SELECT t.id, t.slug, t.name, r.key,
               coalesce(array_agg(rs.scope_code ORDER BY rs.scope_code)
                        FILTER (WHERE rs.scope_code IS NOT NULL), ARRAY[]::text[])
          FROM axon.memberships m
          JOIN axon.tenants t ON t.id = m.tenant_id AND t.status = 'active'
          JOIN axon.roles r   ON r.id = m.role_id
          LEFT JOIN axon.role_scopes rs ON rs.role_id = r.id
         WHERE m.user_id = p_user_id AND m.status = 'active'
         GROUP BY t.id, t.slug, t.name, r.key;
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
END
$$;

CREATE OR REPLACE FUNCTION axon.lookup_api_key(p_prefix text)
    RETURNS TABLE (api_key_id uuid, tenant_id uuid, key_hash bytea, scopes text[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    prev text := current_setting('app.current_tenant_id', true);
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    RETURN QUERY
        SELECT k.id, k.tenant_id, k.key_hash, k.scopes
          FROM axon.api_keys k
          JOIN axon.tenants t ON t.id = k.tenant_id AND t.status = 'active'
         WHERE k.key_prefix = p_prefix
           AND k.revoked_at IS NULL
           AND (k.expires_at IS NULL OR k.expires_at > now());
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
END
$$;

-- Creates a tenant and makes p_owner its owner in one step (signup flow).
-- The owner grant is not subject to assert_can_grant because the tenant does
-- not exist yet from the caller's point of view.
CREATE OR REPLACE FUNCTION axon.provision_tenant(p_slug text, p_name text, p_owner uuid)
    RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    prev   text := current_setting('app.current_tenant_id', true);
    new_id uuid;
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    IF NOT EXISTS (SELECT 1 FROM axon.users u WHERE u.id = p_owner AND u.is_active) THEN
        RAISE EXCEPTION 'axon: owner % is not an active user', p_owner
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    INSERT INTO axon.tenants (slug, name) VALUES (p_slug, p_name) RETURNING id INTO new_id;
    INSERT INTO axon.memberships (tenant_id, user_id, role_id)
    SELECT new_id, p_owner, r.id FROM axon.roles r WHERE r.tenant_id IS NULL AND r.key = 'owner';
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
    RETURN new_id;
END
$$;

-- -----------------------------------------------------------------------------
-- Row level security (fail-closed)
-- -----------------------------------------------------------------------------
ALTER TABLE axon.tenants                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.users                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.roles                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.role_scopes             ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.memberships             ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.api_keys                ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.integration_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.webhook_endpoints       ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.webhook_deliveries      ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.audit_events            ENABLE ROW LEVEL SECURITY;

ALTER TABLE axon.tenants                 FORCE ROW LEVEL SECURITY;
ALTER TABLE axon.users                   FORCE ROW LEVEL SECURITY;
ALTER TABLE axon.roles                   FORCE ROW LEVEL SECURITY;
ALTER TABLE axon.role_scopes             FORCE ROW LEVEL SECURITY;
ALTER TABLE axon.memberships             FORCE ROW LEVEL SECURITY;
ALTER TABLE axon.api_keys                FORCE ROW LEVEL SECURITY;
ALTER TABLE axon.integration_credentials FORCE ROW LEVEL SECURITY;
ALTER TABLE axon.webhook_endpoints       FORCE ROW LEVEL SECURITY;
ALTER TABLE axon.webhook_deliveries      FORCE ROW LEVEL SECURITY;
ALTER TABLE axon.audit_events            FORCE ROW LEVEL SECURITY;

-- The schema owner runs provisioning and migrations outside any tenant. FORCE
-- applies the policies to it too, so it gets an explicit, owner-only policy.
-- axon_app is never the owner, so this policy never matches for the runtime.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['tenants', 'users', 'roles', 'role_scopes', 'memberships',
                             'api_keys', 'integration_credentials', 'webhook_endpoints',
                             'webhook_deliveries', 'audit_events'] LOOP
        EXECUTE format('DROP POLICY IF EXISTS owner_maintenance ON axon.%I', t);
        EXECUTE format(
            'CREATE POLICY owner_maintenance ON axon.%I AS PERMISSIVE FOR ALL TO %I '
            'USING (axon.current_tenant_id() IS NULL) WITH CHECK (axon.current_tenant_id() IS NULL)',
            t, (SELECT tableowner FROM pg_tables WHERE schemaname = 'axon' AND tablename = t));
    END LOOP;
END
$$;

-- tenants
DROP POLICY IF EXISTS tenant_select ON axon.tenants;
CREATE POLICY tenant_select ON axon.tenants FOR SELECT TO axon_app
    USING (id = axon.current_tenant_id());
DROP POLICY IF EXISTS tenant_update ON axon.tenants;
CREATE POLICY tenant_update ON axon.tenants FOR UPDATE TO axon_app
    USING (id = axon.current_tenant_id() AND axon.has_scope('tenant:manage'))
    WITH CHECK (id = axon.current_tenant_id());

-- users: yourself, plus people who share the current tenant
DROP POLICY IF EXISTS user_select ON axon.users;
CREATE POLICY user_select ON axon.users FOR SELECT TO axon_app
    USING (
        id = axon.current_user_id()
        OR EXISTS (SELECT 1 FROM axon.memberships m
                    WHERE m.user_id = users.id AND m.tenant_id = axon.current_tenant_id())
    );
DROP POLICY IF EXISTS user_insert ON axon.users;
CREATE POLICY user_insert ON axon.users FOR INSERT TO axon_app
    WITH CHECK (true);
DROP POLICY IF EXISTS user_update_self ON axon.users;
CREATE POLICY user_update_self ON axon.users FOR UPDATE TO axon_app
    USING (id = axon.current_user_id())
    WITH CHECK (id = axon.current_user_id());

-- roles: system roles are visible to everyone in a tenant, never writable
DROP POLICY IF EXISTS role_select ON axon.roles;
CREATE POLICY role_select ON axon.roles FOR SELECT TO axon_app
    USING (axon.current_tenant_id() IS NOT NULL
           AND (tenant_id IS NULL OR tenant_id = axon.current_tenant_id()));
DROP POLICY IF EXISTS role_write ON axon.roles;
CREATE POLICY role_write ON axon.roles FOR ALL TO axon_app
    USING (tenant_id = axon.current_tenant_id() AND axon.has_scope('roles:manage'))
    WITH CHECK (tenant_id = axon.current_tenant_id() AND NOT is_system
                AND axon.has_scope('roles:manage'));

-- role_scopes follow their role
DROP POLICY IF EXISTS role_scope_select ON axon.role_scopes;
CREATE POLICY role_scope_select ON axon.role_scopes FOR SELECT TO axon_app
    USING (EXISTS (SELECT 1 FROM axon.roles r WHERE r.id = role_scopes.role_id));
DROP POLICY IF EXISTS role_scope_write ON axon.role_scopes;
CREATE POLICY role_scope_write ON axon.role_scopes FOR ALL TO axon_app
    USING (axon.has_scope('roles:manage')
           AND EXISTS (SELECT 1 FROM axon.roles r
                        WHERE r.id = role_scopes.role_id AND r.tenant_id = axon.current_tenant_id()))
    WITH CHECK (axon.has_scope('roles:manage')
                AND EXISTS (SELECT 1 FROM axon.roles r
                             WHERE r.id = role_scopes.role_id AND r.tenant_id = axon.current_tenant_id()));

-- memberships
DROP POLICY IF EXISTS membership_select ON axon.memberships;
CREATE POLICY membership_select ON axon.memberships FOR SELECT TO axon_app
    USING (tenant_id = axon.current_tenant_id());
DROP POLICY IF EXISTS membership_write ON axon.memberships;
CREATE POLICY membership_write ON axon.memberships FOR ALL TO axon_app
    USING (tenant_id = axon.current_tenant_id() AND axon.has_scope('members:manage'))
    WITH CHECK (tenant_id = axon.current_tenant_id() AND axon.has_scope('members:manage'));

-- api_keys
DROP POLICY IF EXISTS api_key_select ON axon.api_keys;
CREATE POLICY api_key_select ON axon.api_keys FOR SELECT TO axon_app
    USING (tenant_id = axon.current_tenant_id() AND axon.has_scope('api_keys:manage'));
DROP POLICY IF EXISTS api_key_write ON axon.api_keys;
CREATE POLICY api_key_write ON axon.api_keys FOR ALL TO axon_app
    USING (tenant_id = axon.current_tenant_id() AND axon.has_scope('api_keys:manage'))
    WITH CHECK (tenant_id = axon.current_tenant_id() AND axon.has_scope('api_keys:manage'));

-- integration_credentials
DROP POLICY IF EXISTS credential_select ON axon.integration_credentials;
CREATE POLICY credential_select ON axon.integration_credentials FOR SELECT TO axon_app
    USING (tenant_id = axon.current_tenant_id() AND axon.has_scope('integrations:read'));
DROP POLICY IF EXISTS credential_write ON axon.integration_credentials;
CREATE POLICY credential_write ON axon.integration_credentials FOR ALL TO axon_app
    USING (tenant_id = axon.current_tenant_id() AND axon.has_scope('integrations:manage'))
    WITH CHECK (tenant_id = axon.current_tenant_id() AND axon.has_scope('integrations:manage'));

-- webhook_endpoints: readable in-tenant (the receiver needs the secret),
-- writable only with webhooks:manage
DROP POLICY IF EXISTS webhook_select ON axon.webhook_endpoints;
CREATE POLICY webhook_select ON axon.webhook_endpoints FOR SELECT TO axon_app
    USING (tenant_id = axon.current_tenant_id());
DROP POLICY IF EXISTS webhook_write ON axon.webhook_endpoints;
CREATE POLICY webhook_write ON axon.webhook_endpoints FOR ALL TO axon_app
    USING (tenant_id = axon.current_tenant_id() AND axon.has_scope('webhooks:manage'))
    WITH CHECK (tenant_id = axon.current_tenant_id() AND axon.has_scope('webhooks:manage'));

-- webhook_deliveries: insert/read in-tenant only
DROP POLICY IF EXISTS delivery_select ON axon.webhook_deliveries;
CREATE POLICY delivery_select ON axon.webhook_deliveries FOR SELECT TO axon_app
    USING (tenant_id = axon.current_tenant_id());
DROP POLICY IF EXISTS delivery_insert ON axon.webhook_deliveries;
CREATE POLICY delivery_insert ON axon.webhook_deliveries FOR INSERT TO axon_app
    WITH CHECK (tenant_id = axon.current_tenant_id());

-- audit_events: anyone in the tenant may append; reading needs audit:read
DROP POLICY IF EXISTS audit_select ON axon.audit_events;
CREATE POLICY audit_select ON axon.audit_events FOR SELECT TO axon_app
    USING (tenant_id = axon.current_tenant_id() AND axon.has_scope('audit:read'));
DROP POLICY IF EXISTS audit_insert ON axon.audit_events;
CREATE POLICY audit_insert ON axon.audit_events FOR INSERT TO axon_app
    WITH CHECK (tenant_id = axon.current_tenant_id());

-- -----------------------------------------------------------------------------
-- Privileges for the runtime role (least privilege)
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'axon_app') THEN
        RAISE NOTICE 'axon: role axon_app missing, skipping grants';
        RETURN;
    END IF;

    REVOKE ALL ON SCHEMA axon FROM PUBLIC;
    REVOKE ALL ON ALL TABLES IN SCHEMA axon FROM PUBLIC;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA axon FROM PUBLIC;

    GRANT USAGE ON SCHEMA axon TO axon_app;

    GRANT SELECT                         ON axon.scopes                  TO axon_app;
    GRANT SELECT, UPDATE                 ON axon.tenants                 TO axon_app;
    GRANT SELECT, INSERT, UPDATE         ON axon.users                   TO axon_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON axon.roles                   TO axon_app;
    GRANT SELECT, INSERT, DELETE         ON axon.role_scopes             TO axon_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON axon.memberships             TO axon_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON axon.api_keys                TO axon_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON axon.integration_credentials TO axon_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON axon.webhook_endpoints       TO axon_app;
    GRANT SELECT, INSERT                 ON axon.webhook_deliveries      TO axon_app;
    GRANT SELECT, INSERT                 ON axon.audit_events            TO axon_app;
    GRANT USAGE ON ALL SEQUENCES IN SCHEMA axon TO axon_app;

    -- Column-level: the runtime may never rewrite a user's password hash or
    -- MFA flag through plain UPDATE on someone else's row; RLS already limits
    -- UPDATE to the caller's own row.
    REVOKE UPDATE ON axon.users FROM axon_app;
    GRANT UPDATE (display_name, password_hash, mfa_enabled, last_login_at, email_verified_at)
        ON axon.users TO axon_app;

    GRANT EXECUTE ON FUNCTION
        axon.current_tenant_id(), axon.current_user_id(), axon.current_scopes(),
        axon.scope_covers(text[], text), axon.has_scope(text), axon.assert_can_grant(text[]),
        axon.find_login_user(text), axon.user_tenants(uuid), axon.lookup_api_key(text),
        axon.provision_tenant(text, text, uuid)
    TO axon_app;
END
$$;

COMMIT;
