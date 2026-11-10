-- =============================================================================
-- Axon Automation Studio — Core Database Schema Initialization (Production-Grade)
-- =============================================================================
--
-- Schema `axon`:
--   organizations            tenants
--   users                    belong to exactly one organization, with a role
--   roles / scopes /         role catalog (admin, manager, member + custom
--   role_scopes              per-organization roles) and the scopes each grants
--   api_keys                 HMAC digest only, scoped, owned by a user
--   ai_cost_metrics          FinOps: tokens and cost per model call (append-only)
--   integration_credentials  third-party tokens, ciphertext only
--   webhook_endpoints /      inbound webhooks: encrypted signing secret and a
--   webhook_deliveries       replay ledger
--   refresh_tokens           rotating refresh tokens (hash only, family reuse detection)
--   audit_events             append-only audit log
--
-- Security model
-- --------------
-- * ROW LEVEL SECURITY is enabled AND forced on every table, so it applies to
--   the table owner too.
-- * Policies are FAIL-CLOSED: with `app.current_tenant_id` unset a query sees
--   zero rows and every write is rejected.
-- * The application switches to the NOLOGIN, NOBYPASSRLS role `axon_app` in
--   every transaction (`SET LOCAL ROLE axon_app`, done by app/core/db.py), so
--   even a superuser login is held to the policies.
-- * Scopes are enforced by the API layer and again here through
--   `axon.has_scope()`. Nobody can give a user, role or API key a scope they
--   do not hold themselves, and an organization never loses its last admin.
-- * Secrets are never stored in plaintext: integration tokens and webhook
--   secrets must be Axon ciphertext (`axv1.<key-id>.<payload>` from
--   app/core/config.py's TokenCipher); API keys are stored as a hex
--   HMAC-SHA256 digest.
-- * Pre-authentication lookups (login, API key) and organization signup go
--   through narrow SECURITY DEFINER functions instead of opening the tables.
--
-- Requirements: PostgreSQL 15+ (UNIQUE NULLS NOT DISTINCT). UUIDs come from the
-- built-in gen_random_uuid() (PostgreSQL 13+), so uuid-ossp is not needed.
-- Idempotent: safe to run repeatedly, as the database/schema owner. Creating the
-- `axon_app` role needs CREATEROLE; without it the script stops and prints the
-- statements a DBA has to run first.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS axon;
COMMENT ON SCHEMA axon IS 'Axon Automation Studio core: organizations, RBAC, FinOps, secrets, audit.';

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

-- Let the login running this script switch into axon_app.
DO $$
BEGIN
    IF NOT pg_has_role(current_user, 'axon_app', 'MEMBER') THEN
        EXECUTE format('GRANT axon_app TO %I', current_user);
    END IF;
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'axon: could not grant axon_app to %, grant it manually', current_user;
END
$$;

-- -----------------------------------------------------------------------------
-- Session context helpers
-- -----------------------------------------------------------------------------
-- Set per transaction by app/core/db.py with set_config(..., is_local => true),
-- so they never leak to the next borrower of a pooled connection. A connection
-- that once had a local value reports '' afterwards, hence nullif().

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

-- Scopes are written resource:action. `held` covers `required` exactly, through
-- the global wildcard '*', or through a resource wildcard such as 'workflows:*'.
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
-- Enforced only inside an organization context; trusted provisioning code that
-- runs with no organization set is exempt.
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

CREATE OR REPLACE FUNCTION axon.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END
$$;

-- -----------------------------------------------------------------------------
-- 1. Organizations (tenants)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.organizations (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    name        varchar(255) NOT NULL CHECK (length(btrim(name)) > 0),
    slug        varchar(100) NOT NULL UNIQUE
                             CHECK (slug ~ '^[a-z0-9](?:[a-z0-9-]{1,98}[a-z0-9])$'),
    plan        varchar(20)  NOT NULL DEFAULT 'free'
                             CHECK (plan IN ('free', 'starter', 'pro', 'team', 'enterprise')),
    is_active   boolean      NOT NULL DEFAULT true,
    settings    jsonb        NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(settings) = 'object'),
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- 2. RBAC catalog: scopes, roles, role -> scope grants
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.scopes (
    code         text PRIMARY KEY CHECK (code ~ '^[a-z][a-z_]*:(?:[a-z][a-z_]*|\*)$'),
    description  text NOT NULL
);

-- organization_id NULL = built-in role shared by every organization (read-only).
CREATE TABLE IF NOT EXISTS axon.roles (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  uuid        REFERENCES axon.organizations (id) ON DELETE CASCADE,
    key              varchar(50) NOT NULL CHECK (key ~ '^[a-z][a-z0-9_]{1,49}$'),
    name             varchar(80) NOT NULL CHECK (length(btrim(name)) > 0),
    description      text,
    is_system        boolean     NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT roles_org_key_key UNIQUE NULLS NOT DISTINCT (organization_id, key),
    CONSTRAINT roles_system_has_no_org CHECK (is_system = (organization_id IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_roles_org ON axon.roles (organization_id);

CREATE TABLE IF NOT EXISTS axon.role_scopes (
    role_id     uuid NOT NULL REFERENCES axon.roles (id) ON DELETE CASCADE,
    scope_code  text NOT NULL REFERENCES axon.scopes (code) ON DELETE CASCADE,
    PRIMARY KEY (role_id, scope_code)
);

-- Scopes granted by role `p_role` inside organization `p_org` (custom role of
-- that organization first, then the built-in role with the same key).
CREATE OR REPLACE FUNCTION axon.role_scope_list(p_org uuid, p_role text) RETURNS text[]
    LANGUAGE sql STABLE
    SET search_path = pg_catalog
AS $$
    SELECT coalesce(array_agg(rs.scope_code ORDER BY rs.scope_code), ARRAY[]::text[])
      FROM axon.role_scopes rs
     WHERE rs.role_id = (
           SELECT r.id FROM axon.roles r
            WHERE r.key = p_role AND (r.organization_id = p_org OR r.organization_id IS NULL)
            ORDER BY r.organization_id NULLS LAST
            LIMIT 1)
$$;

-- -----------------------------------------------------------------------------
-- 3. Users (one organization each; email unique within the organization)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.users (
    id                 uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id    uuid         NOT NULL REFERENCES axon.organizations (id) ON DELETE CASCADE,
    email              varchar(255) NOT NULL
                                    CHECK (email = lower(btrim(email)))
                                    CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    hashed_password    varchar(255) NOT NULL CHECK (length(hashed_password) >= 20),
    full_name          varchar(255),
    role               varchar(50)  NOT NULL DEFAULT 'member',
    is_active          boolean      NOT NULL DEFAULT true,
    email_verified_at  timestamptz,
    mfa_enabled        boolean      NOT NULL DEFAULT false,
    last_login_at      timestamptz,
    created_at         timestamptz  NOT NULL DEFAULT now(),
    updated_at         timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uniq_org_email UNIQUE (organization_id, email),
    CONSTRAINT users_id_org_key UNIQUE (id, organization_id)
);
CREATE INDEX IF NOT EXISTS idx_users_org ON axon.users (organization_id);

-- -----------------------------------------------------------------------------
-- 4. API keys and scopes
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.api_keys (
    id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  uuid         NOT NULL REFERENCES axon.organizations (id) ON DELETE CASCADE,
    user_id          uuid         NOT NULL,
    name             varchar(100) NOT NULL CHECK (length(btrim(name)) > 0),
    key_prefix       varchar(16)  NOT NULL CHECK (key_prefix ~ '^axk_[A-Za-z0-9]{4,12}$'),
    hashed_key       varchar(255) NOT NULL UNIQUE CHECK (hashed_key ~ '^[0-9a-f]{64}$'),
    scopes           text[]       NOT NULL DEFAULT '{workflows:read}'::text[]
                                  CHECK (array_position(scopes, NULL) IS NULL),
    expires_at       timestamptz,
    is_active        boolean      NOT NULL DEFAULT true,
    created_at       timestamptz  NOT NULL DEFAULT now(),
    last_used_at     timestamptz,
    -- The key's owner must belong to the key's organization.
    FOREIGN KEY (user_id, organization_id) REFERENCES axon.users (id, organization_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_api_keys_org ON axon.api_keys (organization_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON axon.api_keys (key_prefix);

-- -----------------------------------------------------------------------------
-- 5. AI cost metrics (FinOps) — append-only
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.ai_cost_metrics (
    id                  uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid          NOT NULL REFERENCES axon.organizations (id) ON DELETE CASCADE,
    user_id             uuid          REFERENCES axon.users (id) ON DELETE SET NULL,
    model_name          varchar(100)  NOT NULL CHECK (length(btrim(model_name)) > 0),
    provider            varchar(100)  NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_-]{1,99}$'),
    prompt_tokens       integer       NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
    completion_tokens   integer       NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
    estimated_cost_usd  numeric(10,6) NOT NULL DEFAULT 0 CHECK (estimated_cost_usd >= 0),
    created_at          timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cost_org_date ON axon.ai_cost_metrics (organization_id, created_at);

-- -----------------------------------------------------------------------------
-- 6. Integration credentials — ciphertext only
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.integration_credentials (
    id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  uuid         NOT NULL REFERENCES axon.organizations (id) ON DELETE CASCADE,
    provider         varchar(40)  NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_]{1,39}$'),
    account_label    varchar(120) NOT NULL DEFAULT 'default' CHECK (length(btrim(account_label)) > 0),
    ciphertext       text         NOT NULL
                                  CHECK (ciphertext ~ '^axv1\.[A-Za-z0-9_-]{1,32}\.[A-Za-z0-9_-]+$'),
    key_id           varchar(32)  NOT NULL CHECK (key_id ~ '^[A-Za-z0-9_-]{1,32}$'),
    granted_scopes   text[]       NOT NULL DEFAULT ARRAY[]::text[],
    expires_at       timestamptz,
    created_by       uuid         REFERENCES axon.users (id) ON DELETE SET NULL,
    created_at       timestamptz  NOT NULL DEFAULT now(),
    updated_at       timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT integration_credentials_key_matches CHECK (split_part(ciphertext, '.', 2) = key_id),
    CONSTRAINT integration_credentials_account_key UNIQUE (organization_id, provider, account_label)
);
CREATE INDEX IF NOT EXISTS idx_credentials_key ON axon.integration_credentials (key_id);

-- -----------------------------------------------------------------------------
-- 7. Inbound webhooks: encrypted signing secret + replay ledger
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.webhook_endpoints (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id    uuid        NOT NULL REFERENCES axon.organizations (id) ON DELETE CASCADE,
    name               varchar(80) NOT NULL CHECK (length(btrim(name)) > 0),
    secret_ciphertext  text        NOT NULL
                                   CHECK (secret_ciphertext ~ '^axv1\.[A-Za-z0-9_-]{1,32}\.[A-Za-z0-9_-]+$'),
    tolerance_seconds  integer     NOT NULL DEFAULT 300 CHECK (tolerance_seconds BETWEEN 30 AND 900),
    is_active          boolean     NOT NULL DEFAULT true,
    created_by         uuid        REFERENCES axon.users (id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT webhook_endpoints_id_org_key UNIQUE (id, organization_id)
);
CREATE INDEX IF NOT EXISTS idx_webhooks_org ON axon.webhook_endpoints (organization_id);

-- A delivery id is accepted once per endpoint: a replay is a unique violation.
CREATE TABLE IF NOT EXISTS axon.webhook_deliveries (
    endpoint_id      uuid         NOT NULL,
    organization_id  uuid         NOT NULL,
    delivery_id      varchar(128) NOT NULL CHECK (length(delivery_id) >= 8),
    received_at      timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (endpoint_id, delivery_id),
    FOREIGN KEY (endpoint_id, organization_id)
        REFERENCES axon.webhook_endpoints (id, organization_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_deliveries_received ON axon.webhook_deliveries (received_at);

-- -----------------------------------------------------------------------------
-- 8. Refresh tokens (rotation with reuse detection; only a hex SHA-256 is stored)
-- -----------------------------------------------------------------------------
-- Every refresh issues a new token in the same family and marks the old one
-- used. Presenting a used token again means it was stolen: the auth layer
-- revokes the whole family.
CREATE TABLE IF NOT EXISTS axon.refresh_tokens (
    id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  uuid         NOT NULL,
    user_id          uuid         NOT NULL,
    family_id        uuid         NOT NULL,
    token_hash       varchar(64)  NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    expires_at       timestamptz  NOT NULL,
    used_at          timestamptz,
    revoked_at       timestamptz,
    revoked_reason   varchar(40)  CHECK (revoked_reason IS NULL OR revoked_reason ~ '^[a-z_]{2,40}$'),
    created_at       timestamptz  NOT NULL DEFAULT now(),
    ip_address       inet,
    user_agent       varchar(512),
    FOREIGN KEY (user_id, organization_id) REFERENCES axon.users (id, organization_id) ON DELETE CASCADE,
    CONSTRAINT refresh_tokens_expiry_after_creation CHECK (expires_at > created_at),
    CONSTRAINT refresh_tokens_reason_with_revocation CHECK ((revoked_at IS NULL) = (revoked_reason IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_refresh_family ON axon.refresh_tokens (family_id);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON axon.refresh_tokens (organization_id, user_id);

-- -----------------------------------------------------------------------------
-- 8. Audit log — append-only
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS axon.audit_events (
    id                bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id   uuid        NOT NULL REFERENCES axon.organizations (id) ON DELETE CASCADE,
    actor_user_id     uuid,
    actor_api_key_id  uuid,
    action            varchar(100) NOT NULL CHECK (action ~ '^[a-z][a-z0-9_.:-]{2,99}$'),
    resource_type     varchar(60),
    resource_id       text,
    ip_address        inet,
    user_agent        varchar(512),
    metadata          jsonb       NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_org_date ON axon.audit_events (organization_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- Integrity triggers
-- -----------------------------------------------------------------------------

-- Append-only tables: only an organization deletion may remove rows.
CREATE OR REPLACE FUNCTION axon.forbid_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND NOT EXISTS (SELECT 1 FROM axon.organizations o WHERE o.id = OLD.organization_id) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'axon: % is append-only (% rejected)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$$;

-- Users: the role must exist for the organization; the caller may not hand
-- out a role carrying scopes they do not hold; users never change
-- organization; an organization keeps at least one active admin.
CREATE OR REPLACE FUNCTION axon.guard_user() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
DECLARE
    admins_left integer;
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        IF TG_OP = 'UPDATE' AND NEW.organization_id <> OLD.organization_id THEN
            RAISE EXCEPTION 'axon: a user cannot move between organizations'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM axon.roles r
                        WHERE r.key = NEW.role
                          AND (r.organization_id IS NULL OR r.organization_id = NEW.organization_id)) THEN
            RAISE EXCEPTION 'axon: unknown role "%"', NEW.role USING ERRCODE = 'foreign_key_violation';
        END IF;
        IF TG_OP = 'INSERT' OR NEW.role IS DISTINCT FROM OLD.role THEN
            PERFORM axon.assert_can_grant(axon.role_scope_list(NEW.organization_id, NEW.role));
        END IF;
    END IF;

    IF TG_OP IN ('UPDATE', 'DELETE')
       AND OLD.role = 'admin' AND OLD.is_active
       AND (TG_OP = 'DELETE' OR NEW.role <> 'admin' OR NOT NEW.is_active)
       AND EXISTS (SELECT 1 FROM axon.organizations o WHERE o.id = OLD.organization_id) THEN
        SELECT count(*) INTO admins_left
          FROM axon.users u
         WHERE u.organization_id = OLD.organization_id AND u.role = 'admin'
           AND u.is_active AND u.id <> OLD.id;
        IF admins_left = 0 THEN
            RAISE EXCEPTION 'axon: an organization must keep at least one active admin'
                USING ERRCODE = 'check_violation';
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
     WHERE s <> '*'
       AND s !~ '^[a-z][a-z_]*:\*$'
       AND NOT EXISTS (SELECT 1 FROM axon.scopes c WHERE c.code = s)
     LIMIT 1;
    IF unknown IS NOT NULL THEN
        RAISE EXCEPTION 'axon: unknown scope "%"', unknown USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'INSERT' OR NEW.scopes IS DISTINCT FROM OLD.scopes THEN
        PERFORM axon.assert_can_grant(NEW.scopes);
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.hashed_key <> OLD.hashed_key OR NEW.key_prefix <> OLD.key_prefix
                             OR NEW.organization_id <> OLD.organization_id
                             OR NEW.user_id <> OLD.user_id) THEN
        RAISE EXCEPTION 'axon: api key material, owner and organization are immutable; issue a new key'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['organizations', 'users', 'roles',
                             'integration_credentials', 'webhook_endpoints'] LOOP
        EXECUTE format(
            'CREATE OR REPLACE TRIGGER %I BEFORE UPDATE ON axon.%I '
            'FOR EACH ROW EXECUTE FUNCTION axon.update_updated_at_column()',
            'update_' || t || '_modtime', t);
    END LOOP;
END
$$;

CREATE OR REPLACE TRIGGER users_guard
    BEFORE INSERT OR UPDATE OR DELETE ON axon.users
    FOR EACH ROW EXECUTE FUNCTION axon.guard_user();

CREATE OR REPLACE TRIGGER role_scopes_guard
    BEFORE INSERT OR UPDATE ON axon.role_scopes
    FOR EACH ROW EXECUTE FUNCTION axon.guard_role_scope();

CREATE OR REPLACE TRIGGER api_keys_guard
    BEFORE INSERT OR UPDATE ON axon.api_keys
    FOR EACH ROW EXECUTE FUNCTION axon.guard_api_key();

CREATE OR REPLACE TRIGGER ai_cost_metrics_append_only
    BEFORE UPDATE OR DELETE ON axon.ai_cost_metrics
    FOR EACH ROW EXECUTE FUNCTION axon.forbid_mutation();

CREATE OR REPLACE TRIGGER audit_events_append_only
    BEFORE UPDATE OR DELETE ON axon.audit_events
    FOR EACH ROW EXECUTE FUNCTION axon.forbid_mutation();

-- -----------------------------------------------------------------------------
-- Seed: scope catalog and built-in roles
-- -----------------------------------------------------------------------------
INSERT INTO axon.scopes (code, description) VALUES
    ('organization:read',    'View organization settings'),
    ('organization:manage',  'Change organization settings and plan'),
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
    ('costs:read',           'View AI usage and cost metrics'),
    ('billing:manage',       'Change billing details'),
    ('audit:read',           'Read the audit log')
ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description;

INSERT INTO axon.roles (organization_id, key, name, description, is_system) VALUES
    (NULL, 'admin',   'Admin',   'Full control of the organization',                          true),
    (NULL, 'manager', 'Manager', 'Manage members, integrations, automations and agents',      true),
    (NULL, 'member',  'Member',  'Build and run automations and agents',                      true)
ON CONFLICT ON CONSTRAINT roles_org_key_key DO UPDATE
    SET name = EXCLUDED.name, description = EXCLUDED.description;

INSERT INTO axon.role_scopes (role_id, scope_code)
SELECT r.id, s.code
  FROM axon.roles r
  JOIN axon.scopes s ON (
        r.key = 'admin'
     OR (r.key = 'manager' AND s.code NOT IN ('organization:manage', 'billing:manage', 'roles:manage'))
     OR (r.key = 'member'  AND s.code IN ('organization:read', 'members:read', 'integrations:read',
                                          'workflows:read', 'workflows:write', 'workflows:execute',
                                          'agents:read', 'agents:write', 'agents:execute'))
  )
 WHERE r.organization_id IS NULL
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- Pre-authentication and provisioning functions (SECURITY DEFINER)
-- -----------------------------------------------------------------------------
-- They run as the schema owner, whose only policy (owner_maintenance) requires
-- the organization GUC to be unset, so each clears it for its own work and
-- restores the caller's value. GUC changes are transactional, so an error
-- restores it too. search_path is pinned so callers cannot hijack names.

CREATE OR REPLACE FUNCTION axon.find_login_user(p_org_slug text, p_email text)
    RETURNS TABLE (user_id uuid, organization_id uuid, hashed_password text, role text,
                   is_active boolean, mfa_enabled boolean, scopes text[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    prev text := current_setting('app.current_tenant_id', true);
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    RETURN QUERY
        SELECT u.id, u.organization_id, u.hashed_password::text, u.role::text,
               (u.is_active AND o.is_active), u.mfa_enabled,
               axon.role_scope_list(u.organization_id, u.role)
          FROM axon.users u
          JOIN axon.organizations o ON o.id = u.organization_id
         WHERE o.slug = lower(btrim(p_org_slug))
           AND u.email = lower(btrim(p_email));
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
END
$$;

CREATE OR REPLACE FUNCTION axon.lookup_api_key(p_hashed_key text)
    RETURNS TABLE (api_key_id uuid, organization_id uuid, user_id uuid, scopes text[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    prev text := current_setting('app.current_tenant_id', true);
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    RETURN QUERY
        SELECT k.id, k.organization_id, k.user_id, k.scopes
          FROM axon.api_keys k
          JOIN axon.organizations o ON o.id = k.organization_id AND o.is_active
          JOIN axon.users u ON u.id = k.user_id AND u.is_active
         WHERE k.hashed_key = p_hashed_key
           AND k.is_active
           AND (k.expires_at IS NULL OR k.expires_at > now());
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
END
$$;

-- Refresh: the only credential is the token itself, so the row is found
-- before any organization is known. Writes (mark used, issue next, revoke the
-- family) then happen in a normal session scoped to the returned organization.
CREATE OR REPLACE FUNCTION axon.find_refresh_token(p_token_hash text)
    RETURNS TABLE (token_id uuid, organization_id uuid, user_id uuid, family_id uuid,
                   expires_at timestamptz, used_at timestamptz, revoked_at timestamptz,
                   user_is_active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    prev text := current_setting('app.current_tenant_id', true);
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    RETURN QUERY
        SELECT t.id, t.organization_id, t.user_id, t.family_id, t.expires_at, t.used_at, t.revoked_at,
               (u.is_active AND o.is_active)
          FROM axon.refresh_tokens t
          JOIN axon.users u ON u.id = t.user_id
          JOIN axon.organizations o ON o.id = t.organization_id
         WHERE t.token_hash = p_token_hash;
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
END
$$;

-- Stamps last_used_at for an API key of the current organization, at most
-- once a minute. A key without api_keys:manage cannot update its own row
-- under RLS, so authentication records usage through this function.
CREATE OR REPLACE FUNCTION axon.touch_api_key(p_api_key_id uuid) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    org  uuid := axon.current_tenant_id();
    prev text := current_setting('app.current_tenant_id', true);
BEGIN
    IF org IS NULL THEN
        RAISE EXCEPTION 'axon: touch_api_key needs an organization context'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM set_config('app.current_tenant_id', '', true);
    UPDATE axon.api_keys k
       SET last_used_at = now()
     WHERE k.id = p_api_key_id
       AND k.organization_id = org
       AND (k.last_used_at IS NULL OR k.last_used_at < now() - interval '1 minute');
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
END
$$;

-- Inbound webhook receiver: finds the endpoint's organization and encrypted
-- secret before any organization is known (the sender has no session).
CREATE OR REPLACE FUNCTION axon.lookup_webhook_endpoint(p_endpoint_id uuid)
    RETURNS TABLE (organization_id uuid, secret_ciphertext text, tolerance_seconds integer)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    prev text := current_setting('app.current_tenant_id', true);
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    RETURN QUERY
        SELECT e.organization_id, e.secret_ciphertext, e.tolerance_seconds
          FROM axon.webhook_endpoints e
          JOIN axon.organizations o ON o.id = e.organization_id AND o.is_active
         WHERE e.id = p_endpoint_id AND e.is_active;
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
END
$$;

-- Signup: creates an organization and its first admin in one step.
CREATE OR REPLACE FUNCTION axon.provision_organization(
        p_slug text, p_name text, p_admin_email text, p_hashed_password text, p_full_name text)
    RETURNS TABLE (organization_id uuid, user_id uuid)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog
AS $$
DECLARE
    prev    text := current_setting('app.current_tenant_id', true);
    new_org uuid;
    new_usr uuid;
BEGIN
    PERFORM set_config('app.current_tenant_id', '', true);
    INSERT INTO axon.organizations (slug, name) VALUES (lower(btrim(p_slug)), p_name)
        RETURNING id INTO new_org;
    INSERT INTO axon.users (organization_id, email, hashed_password, full_name, role)
        VALUES (new_org, lower(btrim(p_admin_email)), p_hashed_password, p_full_name, 'admin')
        RETURNING id INTO new_usr;
    PERFORM set_config('app.current_tenant_id', coalesce(prev, ''), true);
    RETURN QUERY SELECT new_org, new_usr;
END
$$;

-- -----------------------------------------------------------------------------
-- Row level security (fail-closed)
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['organizations', 'roles', 'role_scopes', 'users', 'api_keys',
                             'ai_cost_metrics', 'integration_credentials', 'webhook_endpoints',
                             'webhook_deliveries', 'refresh_tokens', 'audit_events'] LOOP
        EXECUTE format('ALTER TABLE axon.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE axon.%I FORCE ROW LEVEL SECURITY', t);
        -- The schema owner (migrations, provisioning) works with no organization
        -- set; FORCE would otherwise lock it out too. axon_app never owns tables,
        -- so this policy never matches for the runtime.
        EXECUTE format('DROP POLICY IF EXISTS owner_maintenance ON axon.%I', t);
        EXECUTE format(
            'CREATE POLICY owner_maintenance ON axon.%I AS PERMISSIVE FOR ALL TO %I '
            'USING (axon.current_tenant_id() IS NULL) WITH CHECK (axon.current_tenant_id() IS NULL)',
            t, (SELECT tableowner FROM pg_tables WHERE schemaname = 'axon' AND tablename = t));
    END LOOP;
END
$$;

-- organizations
DROP POLICY IF EXISTS org_select ON axon.organizations;
CREATE POLICY org_select ON axon.organizations FOR SELECT TO axon_app
    USING (id = axon.current_tenant_id());
DROP POLICY IF EXISTS org_update ON axon.organizations;
CREATE POLICY org_update ON axon.organizations FOR UPDATE TO axon_app
    USING (id = axon.current_tenant_id() AND axon.has_scope('organization:manage'))
    WITH CHECK (id = axon.current_tenant_id());

-- roles: built-in roles visible to every organization, never writable
DROP POLICY IF EXISTS role_select ON axon.roles;
CREATE POLICY role_select ON axon.roles FOR SELECT TO axon_app
    USING (axon.current_tenant_id() IS NOT NULL
           AND (organization_id IS NULL OR organization_id = axon.current_tenant_id()));
DROP POLICY IF EXISTS role_write ON axon.roles;
CREATE POLICY role_write ON axon.roles FOR ALL TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('roles:manage'))
    WITH CHECK (organization_id = axon.current_tenant_id() AND NOT is_system
                AND axon.has_scope('roles:manage'));

-- role_scopes follow their role
DROP POLICY IF EXISTS role_scope_select ON axon.role_scopes;
CREATE POLICY role_scope_select ON axon.role_scopes FOR SELECT TO axon_app
    USING (EXISTS (SELECT 1 FROM axon.roles r WHERE r.id = role_scopes.role_id));
DROP POLICY IF EXISTS role_scope_write ON axon.role_scopes;
CREATE POLICY role_scope_write ON axon.role_scopes FOR ALL TO axon_app
    USING (axon.has_scope('roles:manage')
           AND EXISTS (SELECT 1 FROM axon.roles r
                        WHERE r.id = role_scopes.role_id AND r.organization_id = axon.current_tenant_id()))
    WITH CHECK (axon.has_scope('roles:manage')
                AND EXISTS (SELECT 1 FROM axon.roles r
                             WHERE r.id = role_scopes.role_id AND r.organization_id = axon.current_tenant_id()));

-- users: everyone in the organization is visible; members:manage writes;
-- a user may update their own row (role changes still pass guard_user)
DROP POLICY IF EXISTS user_select ON axon.users;
CREATE POLICY user_select ON axon.users FOR SELECT TO axon_app
    USING (organization_id = axon.current_tenant_id());
DROP POLICY IF EXISTS user_manage ON axon.users;
CREATE POLICY user_manage ON axon.users FOR ALL TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('members:manage'))
    WITH CHECK (organization_id = axon.current_tenant_id() AND axon.has_scope('members:manage'));
DROP POLICY IF EXISTS user_update_self ON axon.users;
CREATE POLICY user_update_self ON axon.users FOR UPDATE TO axon_app
    USING (organization_id = axon.current_tenant_id() AND id = axon.current_user_id())
    WITH CHECK (organization_id = axon.current_tenant_id() AND id = axon.current_user_id());

-- api_keys
DROP POLICY IF EXISTS api_key_access ON axon.api_keys;
CREATE POLICY api_key_access ON axon.api_keys FOR ALL TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('api_keys:manage'))
    WITH CHECK (organization_id = axon.current_tenant_id() AND axon.has_scope('api_keys:manage'));

-- ai_cost_metrics: anyone in the organization records usage; reading needs costs:read
DROP POLICY IF EXISTS cost_select ON axon.ai_cost_metrics;
CREATE POLICY cost_select ON axon.ai_cost_metrics FOR SELECT TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('costs:read'));
DROP POLICY IF EXISTS cost_insert ON axon.ai_cost_metrics;
CREATE POLICY cost_insert ON axon.ai_cost_metrics FOR INSERT TO axon_app
    WITH CHECK (organization_id = axon.current_tenant_id());

-- integration_credentials
DROP POLICY IF EXISTS credential_select ON axon.integration_credentials;
CREATE POLICY credential_select ON axon.integration_credentials FOR SELECT TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('integrations:read'));
DROP POLICY IF EXISTS credential_write ON axon.integration_credentials;
CREATE POLICY credential_write ON axon.integration_credentials FOR ALL TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('integrations:manage'))
    WITH CHECK (organization_id = axon.current_tenant_id() AND axon.has_scope('integrations:manage'));

-- webhook_endpoints: readable in-organization (the receiver needs the secret)
DROP POLICY IF EXISTS webhook_select ON axon.webhook_endpoints;
CREATE POLICY webhook_select ON axon.webhook_endpoints FOR SELECT TO axon_app
    USING (organization_id = axon.current_tenant_id());
DROP POLICY IF EXISTS webhook_write ON axon.webhook_endpoints;
CREATE POLICY webhook_write ON axon.webhook_endpoints FOR ALL TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('webhooks:manage'))
    WITH CHECK (organization_id = axon.current_tenant_id() AND axon.has_scope('webhooks:manage'));

-- webhook_deliveries
DROP POLICY IF EXISTS delivery_select ON axon.webhook_deliveries;
CREATE POLICY delivery_select ON axon.webhook_deliveries FOR SELECT TO axon_app
    USING (organization_id = axon.current_tenant_id());
DROP POLICY IF EXISTS delivery_insert ON axon.webhook_deliveries;
CREATE POLICY delivery_insert ON axon.webhook_deliveries FOR INSERT TO axon_app
    WITH CHECK (organization_id = axon.current_tenant_id());

-- refresh_tokens: a user handles their own; members:manage may revoke anyone's
DROP POLICY IF EXISTS refresh_own ON axon.refresh_tokens;
CREATE POLICY refresh_own ON axon.refresh_tokens FOR ALL TO axon_app
    USING (organization_id = axon.current_tenant_id() AND user_id = axon.current_user_id())
    WITH CHECK (organization_id = axon.current_tenant_id() AND user_id = axon.current_user_id());
DROP POLICY IF EXISTS refresh_manage ON axon.refresh_tokens;
CREATE POLICY refresh_manage ON axon.refresh_tokens FOR SELECT TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('members:manage'));
DROP POLICY IF EXISTS refresh_revoke ON axon.refresh_tokens;
CREATE POLICY refresh_revoke ON axon.refresh_tokens FOR UPDATE TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('members:manage'))
    WITH CHECK (organization_id = axon.current_tenant_id());

-- audit_events
DROP POLICY IF EXISTS audit_select ON axon.audit_events;
CREATE POLICY audit_select ON axon.audit_events FOR SELECT TO axon_app
    USING (organization_id = axon.current_tenant_id() AND axon.has_scope('audit:read'));
DROP POLICY IF EXISTS audit_insert ON axon.audit_events;
CREATE POLICY audit_insert ON axon.audit_events FOR INSERT TO axon_app
    WITH CHECK (organization_id = axon.current_tenant_id());

-- -----------------------------------------------------------------------------
-- Privileges for the runtime role (least privilege)
-- -----------------------------------------------------------------------------
REVOKE ALL ON SCHEMA axon FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA axon FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA axon FROM PUBLIC;

GRANT USAGE ON SCHEMA axon TO axon_app;

GRANT SELECT                         ON axon.scopes                  TO axon_app;
GRANT SELECT                         ON axon.organizations           TO axon_app;
GRANT UPDATE (name, plan, is_active, settings) ON axon.organizations TO axon_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON axon.roles                   TO axon_app;
GRANT SELECT, INSERT, DELETE         ON axon.role_scopes             TO axon_app;
GRANT SELECT, INSERT, DELETE         ON axon.users                   TO axon_app;
GRANT UPDATE (email, hashed_password, full_name, role, is_active, email_verified_at,
              mfa_enabled, last_login_at) ON axon.users              TO axon_app;
GRANT SELECT, INSERT, DELETE         ON axon.api_keys                TO axon_app;
GRANT UPDATE (name, scopes, expires_at, is_active, last_used_at)
                                     ON axon.api_keys                TO axon_app;
GRANT SELECT, INSERT                 ON axon.ai_cost_metrics         TO axon_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON axon.integration_credentials TO axon_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON axon.webhook_endpoints       TO axon_app;
GRANT SELECT, INSERT                 ON axon.webhook_deliveries      TO axon_app;
GRANT SELECT, INSERT                 ON axon.refresh_tokens          TO axon_app;
GRANT UPDATE (used_at, revoked_at, revoked_reason) ON axon.refresh_tokens TO axon_app;
GRANT SELECT, INSERT                 ON axon.audit_events            TO axon_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA axon TO axon_app;

GRANT EXECUTE ON FUNCTION
    axon.current_tenant_id(), axon.current_user_id(), axon.current_scopes(),
    axon.scope_covers(text[], text), axon.has_scope(text), axon.assert_can_grant(text[]),
    axon.role_scope_list(uuid, text),
    axon.find_login_user(text, text), axon.lookup_api_key(text), axon.find_refresh_token(text),
    axon.touch_api_key(uuid), axon.lookup_webhook_endpoint(uuid),
    axon.provision_organization(text, text, text, text, text)
TO axon_app;

COMMIT;
