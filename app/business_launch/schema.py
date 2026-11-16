"""Opt-in schema for Business Launch.

Not registered in app startup. Apply only in an isolated test database until
the migration and RLS policies have been reviewed.
"""
from __future__ import annotations


async def init_business_launch_schema(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS business_launch_projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            created_by_user_id UUID NOT NULL,
            name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
            idea TEXT NOT NULL CHECK (char_length(idea) BETWEEN 10 AND 3000),
            stage TEXT NOT NULL DEFAULT 'IDEA'
                CHECK (stage IN ('IDEA', 'FEASIBILITY', 'BRAND', 'CATALOG',
                                'LAUNCH_PACKAGE', 'PENDING_APPROVAL', 'APPROVED')),
            approved_by_user_id UUID,
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT business_launch_approval_consistency CHECK (
                (stage = 'APPROVED') =
                (approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS business_launch_projects_org_created_idx
            ON business_launch_projects (org_id, created_at DESC);
    """)
