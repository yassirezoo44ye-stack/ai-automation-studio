"""Initial schema — all tables from app.core.db.init_db plus indexes.

Revision ID: 001
Revises:
Create Date: 2026-07-03 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "users",
        sa.Column("id",         sa.UUID(),  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email",      sa.Text(),  nullable=False, unique=True),
        sa.Column("name",       sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "projects",
        sa.Column("id",          sa.UUID(),        primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id",     sa.UUID(),        nullable=False),
        sa.Column("name",        sa.VARCHAR(100),  nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status",      sa.VARCHAR(50),   server_default="active"),
        sa.Column("created_at",  sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at",  sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])
    op.create_index("ix_projects_status",  "projects", ["status"])

    op.create_table(
        "conversations",
        sa.Column("id",         sa.UUID(),       primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.UUID(),       nullable=False),
        sa.Column("title",      sa.VARCHAR(200), nullable=False, server_default="New conversation"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])

    op.create_table(
        "messages",
        sa.Column("id",              sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("role",            sa.VARCHAR(20), nullable=False),
        sa.Column("content",         sa.Text(), nullable=False),
        sa.Column("created_at",      sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_created_at",      "messages", ["created_at"])

    op.create_table(
        "agent_runs",
        sa.Column("id",            sa.UUID(),      primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id",    sa.UUID(),      nullable=False),
        sa.Column("agent_type",    sa.VARCHAR(50), nullable=False),
        sa.Column("input_data",    sa.JSON()),
        sa.Column("output_data",   sa.JSON()),
        sa.Column("status",        sa.VARCHAR(50), server_default="pending"),
        sa.Column("started_at",    sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at",  sa.TIMESTAMP(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_runs_project_id", "agent_runs", ["project_id"])
    op.create_index("ix_agent_runs_status",     "agent_runs", ["status"])

    op.create_table(
        "usage_logs",
        sa.Column("id",         sa.UUID(),       primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id",    sa.UUID(),       nullable=False),
        sa.Column("action",     sa.VARCHAR(100), nullable=False),
        sa.Column("details",    sa.JSON()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_usage_logs_user_id",    "usage_logs", ["user_id"])
    op.create_index("ix_usage_logs_created_at", "usage_logs", ["created_at"])

    op.create_table(
        "subscriptions",
        sa.Column("id",                     sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email",                  sa.Text(), nullable=False, unique=True),
        sa.Column("stripe_customer_id",     sa.Text()),
        sa.Column("stripe_subscription_id", sa.Text()),
        sa.Column("status",                 sa.Text(), server_default="inactive"),
        sa.Column("current_period_end",     sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at",             sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at",             sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "agents",
        sa.Column("id",           sa.UUID(),        primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_email",  sa.Text(),        nullable=False),
        sa.Column("name",         sa.VARCHAR(100),  nullable=False),
        sa.Column("description",  sa.Text()),
        sa.Column("system_prompt",sa.Text()),
        sa.Column("model",        sa.VARCHAR(100),  server_default="claude-sonnet-4-6"),
        sa.Column("temperature",  sa.Float(),       server_default="0.7"),
        sa.Column("max_tokens",   sa.Integer(),     server_default="2048"),
        sa.Column("tools",        sa.JSON(),        server_default="[]"),
        sa.Column("memory",       sa.JSON(),        server_default="{}"),
        sa.Column("created_at",   sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at",   sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_agents_owner_email", "agents", ["owner_email"])

    op.create_table(
        "tasks",
        sa.Column("id",            sa.UUID(),       primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_email",   sa.Text(),       nullable=False),
        sa.Column("title",         sa.VARCHAR(300), nullable=False),
        sa.Column("description",   sa.Text()),
        sa.Column("status",        sa.VARCHAR(50),  server_default="pending"),
        sa.Column("priority",      sa.VARCHAR(20),  server_default="medium"),
        sa.Column("due_date",      sa.TIMESTAMP(timezone=True)),
        sa.Column("recurrence",    sa.VARCHAR(20)),
        sa.Column("source_conv_id",sa.UUID()),
        sa.Column("created_at",    sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at",    sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_tasks_owner_email", "tasks", ["owner_email"])
    op.create_index("ix_tasks_status",      "tasks", ["status"])
    op.create_index("ix_tasks_due_date",    "tasks", ["due_date"])

    op.create_table(
        "audit_logs",
        sa.Column("id",          sa.UUID(),       primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_email", sa.Text(),       nullable=False),
        sa.Column("action",      sa.VARCHAR(100), nullable=False),
        sa.Column("resource",    sa.VARCHAR(100)),
        sa.Column("resource_id", sa.Text()),
        sa.Column("details",     sa.JSON()),
        sa.Column("ip_address",  sa.Text()),
        sa.Column("created_at",  sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_audit_logs_actor_email", "audit_logs", ["actor_email"])
    op.create_index("ix_audit_logs_created_at",  "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_action",      "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("tasks")
    op.drop_table("agents")
    op.drop_table("subscriptions")
    op.drop_table("usage_logs")
    op.drop_table("agent_runs")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("projects")
    op.drop_table("users")
