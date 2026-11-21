-- Draft BYOK rotation checkpoint schema. NOT applied to production.
-- Deploy only after role/privilege review and a tested migration rollback.
CREATE TABLE IF NOT EXISTS ai_credential_rotation_checkpoints (
    org_id UUID NOT NULL,
    user_id UUID NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'verified', 'failed')),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    last_error_code TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id),
    CONSTRAINT rotation_lease_consistency CHECK (
        (status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)
    )
);
ALTER TABLE ai_credential_rotation_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_credential_rotation_checkpoints FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ai_credential_rotation_checkpoints_scope ON ai_credential_rotation_checkpoints;
CREATE POLICY ai_credential_rotation_checkpoints_scope
ON ai_credential_rotation_checkpoints
USING (
    org_id = NULLIF(current_setting('app.byok_org_id', true), '')::uuid
    AND user_id = NULLIF(current_setting('app.byok_user_id', true), '')::uuid
)
WITH CHECK (
    org_id = NULLIF(current_setting('app.byok_org_id', true), '')::uuid
    AND user_id = NULLIF(current_setting('app.byok_user_id', true), '')::uuid
);
-- Deliberately no GRANT here: DBA must explicitly grant the minimum rights
-- to a dedicated restricted worker role after reviewing its authorization.
