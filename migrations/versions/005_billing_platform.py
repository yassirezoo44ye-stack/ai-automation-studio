"""
Billing & Usage Platform.

Adds:
  subscription_plans, billing_events, invoices, invoice_items, payments,
  payment_methods, coupons, credits

Also backfills org_subscriptions/usage_records/usage_limits/usage_events —
these 4 tables already exist on any running deployment (created by the
idempotent boot-time init_*_schema() functions in app/factory.py's
lifespan), but were never captured as an Alembic revision. Backfilling them
here as CREATE TABLE IF NOT EXISTS is a safe no-op where they already
exist, and a real create on a fresh install that only ever runs
`alembic upgrade head` without booting the app first.

NOTE: migrations/versions/002-004 predate this file and are not wired into
Alembic's revision graph correctly (002's down_revision references a
revision id that doesn't match 001's actual id; 003/004 have no
revision/down_revision at all and use a different up(conn)/down(conn)
format instead of upgrade()/downgrade()) — `alembic upgrade head` does not
currently work end-to-end in this repo. That's a pre-existing gap outside
this phase's scope (billing only); this file matches 004's up(conn)/
down(conn) convention for consistency with its immediate predecessor
rather than attempting to repair the unrelated auth/AI-gateway/design-
canvas revisions.
"""

SQL_UP = """
CREATE TABLE IF NOT EXISTS subscription_plans (
    id                   VARCHAR(20)  PRIMARY KEY,
    name                 VARCHAR(60)  NOT NULL,
    price_monthly_cents  BIGINT       NOT NULL DEFAULT 0,
    limits               JSONB        NOT NULL DEFAULT '{}',
    features             TEXT[]       NOT NULL DEFAULT '{}',
    trial_days           INTEGER      NOT NULL DEFAULT 0,
    max_agents           INTEGER      NOT NULL DEFAULT -1,
    max_workflows        INTEGER      NOT NULL DEFAULT -1,
    stripe_price_id      TEXT,
    is_purchasable       BOOLEAN      NOT NULL DEFAULT true,
    sort_order           INTEGER      NOT NULL DEFAULT 0,
    active               BOOLEAN      NOT NULL DEFAULT true,
    updated_by           UUID,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

INSERT INTO subscription_plans (id, name, price_monthly_cents, limits, features, trial_days, max_agents, max_workflows, is_purchasable, sort_order) VALUES
('free', 'Free', 0, '{"tokens":100000,"workflow_executions":50,"api_requests":5000,"storage_mb":200,"embeddings":1000,"marketplace_purchases":0,"seats":1,"active_users":1,"running_agents":1}', '{community_support}', 0, 3, 5, false, 0),
('starter', 'Starter', 1900, '{"tokens":2000000,"workflow_executions":1000,"api_requests":100000,"storage_mb":5000,"embeddings":50000,"marketplace_purchases":-1,"seats":3,"active_users":3,"running_agents":3}', '{email_support,marketplace}', 14, 10, 20, true, 1),
('pro', 'Professional', 4900, '{"tokens":10000000,"workflow_executions":10000,"api_requests":1000000,"storage_mb":50000,"embeddings":500000,"marketplace_purchases":-1,"seats":10,"active_users":10,"running_agents":10}', '{priority_support,marketplace,advanced_analytics,sso}', 14, 50, 100, true, 2),
('team', 'Team', 9900, '{"tokens":50000000,"workflow_executions":100000,"api_requests":10000000,"storage_mb":250000,"embeddings":5000000,"marketplace_purchases":-1,"seats":25,"active_users":25,"running_agents":25}', '{priority_support,marketplace,advanced_analytics,sso,audit_logs,custom_roles}', 14, 200, 500, true, 3),
('enterprise', 'Enterprise', 0, '{"tokens":-1,"workflow_executions":-1,"api_requests":-1,"storage_mb":-1,"embeddings":-1,"marketplace_purchases":-1,"seats":-1,"active_users":-1,"running_agents":-1}', '{dedicated_support,marketplace,advanced_analytics,sso,audit_logs,custom_roles,sla,private_cloud,custom_models}', 0, -1, -1, false, 4)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS org_subscriptions (
    organization_id         UUID PRIMARY KEY,
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT UNIQUE,
    plan_id                 VARCHAR(20) NOT NULL DEFAULT 'free',
    status                  VARCHAR(20) NOT NULL DEFAULT 'inactive',
    current_period_end      TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_org_subs_customer ON org_subscriptions(stripe_customer_id);

CREATE TABLE IF NOT EXISTS usage_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    metric          VARCHAR(40) NOT NULL,
    period          VARCHAR(7)  NOT NULL,
    amount          BIGINT      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, metric, period)
);
CREATE INDEX IF NOT EXISTS idx_usage_org_period ON usage_records(organization_id, period);

CREATE TABLE IF NOT EXISTS usage_limits (
    organization_id UUID NOT NULL,
    metric          VARCHAR(40) NOT NULL,
    override_limit  BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, metric)
);

CREATE TABLE IF NOT EXISTS usage_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    metric          VARCHAR(40) NOT NULL,
    amount          BIGINT NOT NULL,
    ref_type        VARCHAR(40),
    ref_id          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_usage_events_org ON usage_events(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS billing_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stripe_event_id  TEXT UNIQUE NOT NULL,
    event_type       VARCHAR(80) NOT NULL,
    organization_id  UUID REFERENCES organizations(id) ON DELETE SET NULL,
    payload          JSONB NOT NULL,
    processed_at     TIMESTAMPTZ,
    error            TEXT,
    received_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_billing_events_org  ON billing_events(organization_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_events_type ON billing_events(event_type, received_at DESC);

CREATE TABLE IF NOT EXISTS invoices (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    stripe_invoice_id       TEXT UNIQUE NOT NULL,
    stripe_customer_id      TEXT NOT NULL,
    status                  VARCHAR(20) NOT NULL DEFAULT 'draft',
    amount_due_cents        BIGINT NOT NULL DEFAULT 0,
    amount_paid_cents       BIGINT NOT NULL DEFAULT 0,
    currency                VARCHAR(3)  NOT NULL DEFAULT 'usd',
    hosted_invoice_url      TEXT,
    invoice_pdf_url         TEXT,
    period_start            TIMESTAMPTZ,
    period_end              TIMESTAMPTZ,
    paid_at                 TIMESTAMPTZ,
    updated_by              UUID,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(organization_id, created_at DESC) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS invoice_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id          UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description         TEXT,
    quantity            INTEGER NOT NULL DEFAULT 1,
    unit_amount_cents   BIGINT NOT NULL DEFAULT 0,
    amount_cents        BIGINT NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);

CREATE TABLE IF NOT EXISTS payments (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    invoice_id               UUID REFERENCES invoices(id) ON DELETE SET NULL,
    stripe_payment_intent_id TEXT UNIQUE,
    status                   VARCHAR(20) NOT NULL DEFAULT 'pending',
    amount_cents             BIGINT NOT NULL DEFAULT 0,
    currency                 VARCHAR(3)  NOT NULL DEFAULT 'usd',
    failure_message          TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_payments_org ON payments(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS payment_methods (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    stripe_payment_method_id  TEXT UNIQUE NOT NULL,
    brand                     VARCHAR(20),
    last4                     VARCHAR(4),
    exp_month                 SMALLINT,
    exp_year                  SMALLINT,
    is_default                BOOLEAN NOT NULL DEFAULT false,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at                TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_payment_methods_org ON payment_methods(organization_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS coupons (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code                      VARCHAR(40) UNIQUE NOT NULL,
    stripe_promotion_code_id  TEXT,
    percent_off               NUMERIC(5,2),
    amount_off_cents          BIGINT,
    valid_until               TIMESTAMPTZ,
    active                    BOOLEAN NOT NULL DEFAULT true,
    created_by                UUID,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT coupons_discount_type_check CHECK (percent_off IS NOT NULL OR amount_off_cents IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS credits (
    id                                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id                         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    amount_cents                            BIGINT NOT NULL,
    reason                                  TEXT NOT NULL,
    stripe_customer_balance_transaction_id  TEXT,
    created_by                              UUID,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_credits_org ON credits(organization_id, created_at DESC);
"""

SQL_DOWN = """
DROP TABLE IF EXISTS credits;
DROP TABLE IF EXISTS coupons;
DROP TABLE IF EXISTS payment_methods;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS invoice_items;
DROP TABLE IF EXISTS invoices;
DROP TABLE IF EXISTS billing_events;
DROP TABLE IF EXISTS subscription_plans;
"""
# Deliberately does NOT drop org_subscriptions/usage_records/usage_limits/
# usage_events — those predate this revision on every running deployment
# (created by boot-time init) and a "rollback" of this specific revision
# must not destroy pre-existing production billing data it didn't
# introduce.


def up(conn):
    conn.execute(SQL_UP)


def down(conn):
    conn.execute(SQL_DOWN)
