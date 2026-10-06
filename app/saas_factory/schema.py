"""
SaaS Factory — database schema.

One table: saas_factory_projects
  Stores each user-submitted idea + the pipeline's running state + checkpoints.
  RLS is applied by enable_scoped_rls() (tenancy/rls.py) which covers the
  org_id column on this table automatically.
"""
from __future__ import annotations

import asyncpg


async def init_saas_factory_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS saas_factory_projects (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id              UUID NOT NULL
                                    REFERENCES organizations(id) ON DELETE CASCADE,
            created_by_user_id  UUID NOT NULL,
            idea_text           TEXT NOT NULL,
            -- IDEA|BLUEPRINT|BUILDING|TESTING|VERIFYING|DEPLOYING|LIVE|FAILED|CANCELLED
            phase               TEXT NOT NULL DEFAULT 'IDEA',
            -- per-phase outputs, keyed by phase name
            checkpoint          JSONB NOT NULL DEFAULT '{}',
            -- app_builder_apps.id produced in BUILDING phase
            app_builder_app_id  UUID,
            -- flow_creations.id produced in DEPLOYING phase
            flow_creation_id    UUID,
            error_message       TEXT,
            started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at        TIMESTAMPTZ
        );

        CREATE INDEX IF NOT EXISTS saas_factory_projects_org_idx
            ON saas_factory_projects (org_id);

        CREATE INDEX IF NOT EXISTS saas_factory_projects_phase_idx
            ON saas_factory_projects (org_id, phase);
        """
    )

    # Grant pipeline permissions to all active roles
    await conn.execute(
        """
        INSERT INTO role_permissions (role, resource, action)
        VALUES
          ('owner',     'saas_factory', 'create'),
          ('owner',     'saas_factory', 'read'),
          ('owner',     'saas_factory', 'update'),
          ('owner',     'saas_factory', 'delete'),
          ('admin',     'saas_factory', 'create'),
          ('admin',     'saas_factory', 'read'),
          ('admin',     'saas_factory', 'update'),
          ('admin',     'saas_factory', 'delete'),
          ('manager',   'saas_factory', 'create'),
          ('manager',   'saas_factory', 'read'),
          ('manager',   'saas_factory', 'update'),
          ('developer', 'saas_factory', 'create'),
          ('developer', 'saas_factory', 'read'),
          ('developer', 'saas_factory', 'update'),
          ('operator',  'saas_factory', 'read'),
          ('viewer',    'saas_factory', 'read')
        ON CONFLICT DO NOTHING;
        """
    )
