"""
TenancyService — organization lifecycle, membership, RBAC checks.

All methods are async and pool-backed. The service never exposes rows from a
different organization: every query is scoped by organization_id and filters
deleted_at IS NULL.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)

ROLES = ("owner", "admin", "manager", "developer", "operator", "viewer")

# Role hierarchy for management operations: you can only assign roles
# strictly below your own (owners can assign owner).
ROLE_RANK = {r: i for i, r in enumerate(ROLES)}  # owner=0 (highest) … viewer=5


class TenancyError(Exception):
    """Domain error carrying an HTTP-appropriate status code."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or f"org-{secrets.token_hex(4)}"


class TenancyService:
    """Organization / membership / RBAC operations against PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool
        # Small in-process permission cache: (role) -> set[(resource, action)]
        self._perm_cache: dict[str, set[tuple[str, str]]] = {}

    # ── Organizations ─────────────────────────────────────────────────────────

    async def create_organization(
        self, *, name: str, kind: str = "organization", creator_id: str,
    ) -> dict[str, Any]:
        """Create an org and add its creator as owner (single transaction)."""
        if kind not in ("personal", "organization", "enterprise"):
            raise TenancyError(f"invalid kind {kind!r}")
        slug = _slugify(name)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Ensure slug uniqueness with a numeric suffix on collision.
                base, n = slug, 1
                while await conn.fetchval(
                    "SELECT 1 FROM organizations WHERE slug=$1 AND deleted_at IS NULL", slug
                ):
                    n += 1
                    slug = f"{base}-{n}"
                row = await conn.fetchrow(
                    "INSERT INTO organizations (name, slug, kind, created_by, updated_by) "
                    "VALUES ($1,$2,$3,$4,$4) RETURNING *",
                    name, slug, kind, uuid.UUID(creator_id),
                )
                await conn.execute(
                    "INSERT INTO organization_members (organization_id, user_id, role, created_by) "
                    "VALUES ($1,$2,'owner',$2)",
                    row["id"], uuid.UUID(creator_id),
                )
        await self._log(str(row["id"]), creator_id, "organization.created",
                        resource="organization", resource_id=str(row["id"]))
        try:
            from app.core.events import get_event_bus
            await get_event_bus().publish(
                "organization.created", {"name": name, "kind": kind},
                organization_id=str(row["id"]),
            )
        except Exception:
            log.warning("event publish failed for organization.created org=%s", row["id"], exc_info=True)
        return dict(row)

    async def get_organization(self, org_id: str) -> Optional[dict[str, Any]]:
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM organizations WHERE id=$1 AND deleted_at IS NULL",
                uuid.UUID(org_id),
            )
        return dict(row) if row else None

    async def list_organizations_for_user(self, user_id: str) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT o.*, m.role AS my_role
                   FROM organizations o
                   JOIN organization_members m ON m.organization_id = o.id
                   WHERE m.user_id = $1 AND m.deleted_at IS NULL AND o.deleted_at IS NULL
                   ORDER BY o.created_at""",
                uuid.UUID(user_id),
            )
        return [dict(r) for r in rows]

    async def soft_delete_organization(self, org_id: str, actor_id: str) -> None:
        from app.core.db import acquire_scoped
        role = await self.get_member_role(org_id, actor_id)
        if role != "owner":
            raise TenancyError("only the owner can delete an organization", 403)
        async with acquire_scoped(org_id) as conn:
            await conn.execute(
                "UPDATE organizations SET deleted_at=NOW(), updated_by=$2 WHERE id=$1",
                uuid.UUID(org_id), uuid.UUID(actor_id),
            )
        await self._log(org_id, actor_id, "organization.deleted",
                        resource="organization", resource_id=org_id)

    # ── Membership ────────────────────────────────────────────────────────────

    async def get_member_role(self, org_id: str, user_id: str) -> Optional[str]:
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            return await conn.fetchval(
                "SELECT role FROM organization_members "
                "WHERE organization_id=$1 AND user_id=$2 AND deleted_at IS NULL",
                uuid.UUID(org_id), uuid.UUID(user_id),
            )

    async def list_members(self, org_id: str) -> list[dict[str, Any]]:
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            rows = await conn.fetch(
                """SELECT m.id, m.user_id, m.role, m.created_at,
                          u.email, u.name, u.avatar_url
                   FROM organization_members m
                   JOIN users u ON u.id = m.user_id
                   WHERE m.organization_id=$1 AND m.deleted_at IS NULL
                   ORDER BY m.created_at""",
                uuid.UUID(org_id),
            )
        return [dict(r) for r in rows]

    async def change_member_role(
        self, org_id: str, *, actor_id: str, member_user_id: str, new_role: str,
    ) -> None:
        if new_role not in ROLES:
            raise TenancyError(f"invalid role {new_role!r}")
        actor_role = await self.get_member_role(org_id, actor_id)
        if actor_role is None:
            raise TenancyError("not a member of this organization", 403)
        if ROLE_RANK[actor_role] > ROLE_RANK["admin"]:
            raise TenancyError("insufficient permissions to manage members", 403)
        if ROLE_RANK[new_role] < ROLE_RANK[actor_role]:
            raise TenancyError("cannot assign a role above your own", 403)
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            result = await conn.execute(
                "UPDATE organization_members SET role=$3, updated_by=$4, updated_at=NOW() "
                "WHERE organization_id=$1 AND user_id=$2 AND deleted_at IS NULL",
                uuid.UUID(org_id), uuid.UUID(member_user_id), new_role, uuid.UUID(actor_id),
            )
        if result == "UPDATE 0":
            raise TenancyError("member not found", 404)
        await self._log(org_id, actor_id, "member.role_changed",
                        resource="member", resource_id=member_user_id,
                        details={"new_role": new_role})

    async def remove_member(self, org_id: str, *, actor_id: str, member_user_id: str) -> None:
        actor_role = await self.get_member_role(org_id, actor_id)
        if actor_role not in ("owner", "admin"):
            raise TenancyError("insufficient permissions", 403)
        target_role = await self.get_member_role(org_id, member_user_id)
        if target_role == "owner":
            raise TenancyError("the owner cannot be removed", 403)
        from app.core.db import acquire_scoped
        async with acquire_scoped(org_id) as conn:
            await conn.execute(
                "UPDATE organization_members SET deleted_at=NOW(), updated_by=$3 "
                "WHERE organization_id=$1 AND user_id=$2 AND deleted_at IS NULL",
                uuid.UUID(org_id), uuid.UUID(member_user_id), uuid.UUID(actor_id),
            )
        await self._log(org_id, actor_id, "member.removed",
                        resource="member", resource_id=member_user_id)

    # ── Seats ─────────────────────────────────────────────────────────────────

    async def _check_seat_capacity(self, org_id: str) -> None:
        """Raise if the org is already at its plan's seat limit. Counts active
        members plus pending invitations, so sending 5 invites on a 3-seat
        plan fails at invite-time rather than letting all 5 accept later."""
        from app.billing import get_usage_service
        limit = await get_usage_service().get_limit(org_id, "seats")
        if limit < 0:
            return  # unlimited
        async with self._pool.acquire() as conn:
            used = await conn.fetchval(
                """SELECT
                     (SELECT COUNT(*) FROM organization_members
                      WHERE organization_id=$1 AND deleted_at IS NULL) +
                     (SELECT COUNT(*) FROM invitations
                      WHERE organization_id=$1 AND status='pending' AND deleted_at IS NULL)""",
                uuid.UUID(org_id),
            )
        if used >= limit:
            raise TenancyError(
                f"seat limit reached ({used}/{limit}) — upgrade your plan or remove a member", 409,
            )

    # ── Invitations ───────────────────────────────────────────────────────────

    async def create_invitation(
        self, org_id: str, *, actor_id: str, email: str, role: str = "viewer",
        ttl_hours: int = 72,
    ) -> dict[str, Any]:
        if role not in ROLES or role == "owner":
            raise TenancyError(f"cannot invite with role {role!r}")
        actor_role = await self.get_member_role(org_id, actor_id)
        if actor_role not in ("owner", "admin", "manager"):
            raise TenancyError("insufficient permissions to invite", 403)
        await self._check_seat_capacity(org_id)
        token = secrets.token_urlsafe(32)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO invitations (organization_id, email, role, token, expires_at, created_by) "
                "VALUES ($1,$2,$3,$4,$5,$6) RETURNING *",
                uuid.UUID(org_id), email.lower(), role, token,
                datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
                uuid.UUID(actor_id),
            )
        await self._log(org_id, actor_id, "invitation.created",
                        resource="invitation", resource_id=str(row["id"]),
                        details={"email": email, "role": role})
        return dict(row)

    async def accept_invitation(self, *, token: str, user_id: str, user_email: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inv = await conn.fetchrow(
                    "SELECT * FROM invitations WHERE token=$1 AND deleted_at IS NULL FOR UPDATE",
                    token,
                )
                if inv is None:
                    raise TenancyError("invitation not found", 404)
                if inv["status"] != "pending":
                    raise TenancyError(f"invitation is {inv['status']}", 409)
                if inv["expires_at"] < datetime.now(timezone.utc):
                    await conn.execute(
                        "UPDATE invitations SET status='expired', updated_at=NOW() WHERE id=$1",
                        inv["id"],
                    )
                    raise TenancyError("invitation expired", 410)
                if inv["email"] != user_email.lower():
                    raise TenancyError("invitation was issued for a different email", 403)

                # Seat check — skip if this user already holds a seat (accepting
                # just changes their role, doesn't consume a new one). Reuses
                # the same locked transaction for consistency, not a second
                # connection.
                already_member = await conn.fetchval(
                    "SELECT 1 FROM organization_members "
                    "WHERE organization_id=$1 AND user_id=$2 AND deleted_at IS NULL",
                    inv["organization_id"], uuid.UUID(user_id),
                )
                if not already_member:
                    from app.billing import get_usage_service
                    limit = await get_usage_service().get_limit(str(inv["organization_id"]), "seats")
                    if limit >= 0:
                        used = await conn.fetchval(
                            "SELECT COUNT(*) FROM organization_members "
                            "WHERE organization_id=$1 AND deleted_at IS NULL",
                            inv["organization_id"],
                        )
                        if used >= limit:
                            raise TenancyError(
                                f"seat limit reached ({used}/{limit}) — ask an admin to "
                                "upgrade the plan or free a seat", 409,
                            )

                await conn.execute(
                    """INSERT INTO organization_members (organization_id, user_id, role, created_by)
                       VALUES ($1,$2,$3,$4)
                       ON CONFLICT (organization_id, user_id)
                       DO UPDATE SET role=EXCLUDED.role, deleted_at=NULL, updated_at=NOW()""",
                    inv["organization_id"], uuid.UUID(user_id), inv["role"], inv["created_by"],
                )
                await conn.execute(
                    "UPDATE invitations SET status='accepted', updated_at=NOW() WHERE id=$1",
                    inv["id"],
                )
        await self._log(str(inv["organization_id"]), user_id, "invitation.accepted",
                        resource="invitation", resource_id=str(inv["id"]))
        try:
            from app.core.events import get_event_bus
            await get_event_bus().publish(
                "organization.member_added", {"user_id": user_id, "role": inv["role"]},
                organization_id=str(inv["organization_id"]),
            )
        except Exception:
            log.warning("event publish failed for organization.member_added org=%s",
                       inv["organization_id"], exc_info=True)
        return {"organization_id": str(inv["organization_id"]), "role": inv["role"]}

    # ── RBAC ──────────────────────────────────────────────────────────────────

    async def has_permission(
        self, org_id: str, user_id: str, *, resource: str, action: str,
    ) -> bool:
        """Resource-based permission check for a member of an organization."""
        role = await self.get_member_role(org_id, user_id)
        if role is None:
            return False
        perms = await self._permissions_for(role)
        return (
            ("*", "*") in perms
            or ("*", action) in perms
            or (resource, "*") in perms
            or (resource, action) in perms
        )

    async def _permissions_for(self, role: str) -> set[tuple[str, str]]:
        if role not in self._perm_cache:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT resource, action FROM role_permissions WHERE role=$1", role
                )
            self._perm_cache[role] = {(r["resource"], r["action"]) for r in rows}
        return self._perm_cache[role]

    # ── Activity log ──────────────────────────────────────────────────────────

    async def _log(
        self, org_id: str, actor_id: str, action: str, *,
        resource: str | None = None, resource_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        """Best-effort activity record — never breaks the calling path."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO activity_logs (organization_id, actor_id, action, resource, resource_id, details) "
                    "VALUES ($1,$2,$3,$4,$5,$6)",
                    uuid.UUID(org_id), uuid.UUID(actor_id), action, resource, resource_id,
                    json.dumps(details) if details else None,
                )
        except Exception as exc:
            log.debug("activity log write failed: %s", exc)

    async def list_activity(self, org_id: str, limit: int = 100) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM activity_logs WHERE organization_id=$1 "
                "ORDER BY created_at DESC LIMIT $2",
                uuid.UUID(org_id), min(limit, 500),
            )
        return [dict(r) for r in rows]


# ── Singleton wiring ──────────────────────────────────────────────────────────

_service: Optional[TenancyService] = None


def get_tenancy_service(pool: asyncpg.Pool | None = None) -> TenancyService:
    """Return the process-wide TenancyService, creating it on first call."""
    global _service
    if _service is None:
        if pool is None:
            from app.core.db import get_pool
            pool = get_pool()
        _service = TenancyService(pool)
    return _service
