"""Account data export and deletion (privacy rights: access, portability, erasure).

Export walks every table in the current schema that has a ``user_id`` column,
so new features are covered without editing this file, and drops columns whose
names look like credentials. Deletion plans the work first (which orgs go with
the user, which Stripe subscriptions must stop) so that nothing is deleted when
billing cannot be cancelled: a deleted account must never keep being charged.
"""
from __future__ import annotations

import asyncio
import datetime
import decimal
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

EXPORT_FORMAT_VERSION = 1
# Rows per table in one export. Generous for a personal account; keeps a
# runaway log table from producing an unbounded response.
EXPORT_ROW_LIMIT = 5000

# Columns never exported, whatever table they are in.
_SECRET_COLUMN = re.compile(
    r"(password|passwd|secret|token|hash|cipher|encrypted|credential|private|"
    r"nonce|otp|salt|refresh|api_key|key_value|signature)",
    re.IGNORECASE,
)
# Tables that only hold credentials or one-time codes.
_SKIP_TABLES = frozenset({
    "users", "email_verification_tokens", "password_reset_tokens",
    "mfa_secrets", "mfa_challenges", "oauth_transient_slots",
    "career_oauth_states", "plugin_secrets", "integration_credentials",
})
# Billing rows are keyed by e-mail, not user_id.
_EMAIL_TABLES = (("subscriptions", "email"), ("study_purchases", "buyer_email"))

_ACTIVE_SUB_STATUSES = ("active", "trialing", "past_due", "unpaid", "incomplete")


def _json_value(value: Any) -> Any:
    if isinstance(value, (uuid.UUID, decimal.Decimal)):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return value.total_seconds()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None  # binary blobs are not meaningful to a person reading JSON
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def _columns_by_table(conn, key_column: str) -> dict[str, list[str]]:
    rows = await conn.fetch(
        """SELECT c.table_name, c.column_name
             FROM information_schema.columns c
             JOIN information_schema.tables t
               ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = current_schema()
              AND t.table_type = 'BASE TABLE'
              AND c.table_name IN (
                    SELECT table_name FROM information_schema.columns
                     WHERE table_schema = current_schema() AND column_name = $1)
            ORDER BY c.table_name, c.ordinal_position""",
        key_column,
    )
    tables: dict[str, list[str]] = {}
    for r in rows:
        tables.setdefault(r["table_name"], []).append(r["column_name"])
    return tables


async def _select_rows(conn, table: str, columns: list[str], key: str, value: Any) -> list[dict]:
    safe = [c for c in columns if not _SECRET_COLUMN.search(c)]
    if not safe:
        return []
    sql = (
        f"SELECT {', '.join(_quote_ident(c) for c in safe)} FROM {_quote_ident(table)} "
        f"WHERE {_quote_ident(key)} = $1 LIMIT {EXPORT_ROW_LIMIT}"
    )
    rows = await conn.fetch(sql, value)
    return [{k: _json_value(v) for k, v in dict(r).items()} for r in rows]


async def export_user_data(conn, user_id: str) -> dict[str, Any]:
    uid = uuid.UUID(user_id)
    user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)
    if not user:
        raise LookupError("user not found")
    profile = {
        k: _json_value(v) for k, v in dict(user).items() if not _SECRET_COLUMN.search(k)
    }
    data: dict[str, list[dict]] = {}
    for table, columns in (await _columns_by_table(conn, "user_id")).items():
        if table in _SKIP_TABLES:
            continue
        try:
            rows = await _select_rows(conn, table, columns, "user_id", uid)
        except Exception:  # a type mismatch (e.g. TEXT user_id) must not sink the export
            log.warning("data export skipped table %s", table, exc_info=True)
            continue
        if rows:
            data[table] = rows
    tables_with = await _columns_by_table(conn, "email")
    tables_with.update(await _columns_by_table(conn, "buyer_email"))
    for table, key in _EMAIL_TABLES:
        if table in tables_with:
            rows = await _select_rows(conn, table, tables_with[table], key, user["email"])
            if rows:
                data[table] = rows
    return {
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "profile": profile,
        "data": data,
        "notes": (
            "Credentials (password hashes, tokens, secrets) are never included. "
            f"Each table is limited to {EXPORT_ROW_LIMIT} rows."
        ),
    }


# ── Deletion ──────────────────────────────────────────────────────────────────


class AccountDeletionBlocked(Exception):
    def __init__(self, message: str, *, org_names: list[str]):
        super().__init__(message)
        self.org_names = org_names


class BillingCancellationFailed(Exception):
    pass


@dataclass
class DeletionPlan:
    orgs_to_delete: list[uuid.UUID] = field(default_factory=list)
    stripe_subscriptions: list[str] = field(default_factory=list)


async def plan_account_deletion(conn, user_id: str, email: str) -> DeletionPlan:
    """Decide what goes with the account. Raises AccountDeletionBlocked when the
    user is the only owner of an organization that other people still use: that
    organization and its billing belong to them too, so ownership has to move first."""
    uid = uuid.UUID(user_id)
    plan = DeletionPlan()
    owned = await conn.fetch(
        """SELECT o.id, o.name,
                  (SELECT count(*) FROM organization_members x
                    WHERE x.organization_id = o.id AND x.deleted_at IS NULL
                      AND x.user_id <> $1) AS others,
                  (SELECT count(*) FROM organization_members x
                    WHERE x.organization_id = o.id AND x.deleted_at IS NULL
                      AND x.user_id <> $1 AND x.role = 'owner') AS other_owners
             FROM organizations o
             JOIN organization_members m ON m.organization_id = o.id
            WHERE m.user_id = $1 AND m.role = 'owner'
              AND m.deleted_at IS NULL AND o.deleted_at IS NULL""",
        uid,
    )
    blocked = [r["name"] for r in owned if r["others"] and not r["other_owners"]]
    if blocked:
        raise AccountDeletionBlocked(
            "Transfer ownership of these organizations, or remove their other "
            "members, before deleting your account.",
            org_names=blocked,
        )
    plan.orgs_to_delete = [r["id"] for r in owned if not r["others"]]
    if plan.orgs_to_delete:
        rows = await conn.fetch(
            """SELECT stripe_subscription_id FROM org_subscriptions
                WHERE organization_id = ANY($1::uuid[])
                  AND stripe_subscription_id IS NOT NULL AND status = ANY($2::text[])""",
            plan.orgs_to_delete, list(_ACTIVE_SUB_STATUSES),
        )
        plan.stripe_subscriptions += [r["stripe_subscription_id"] for r in rows]
    if await conn.fetchval("SELECT to_regclass('subscriptions') IS NOT NULL"):
        rows = await conn.fetch(
            """SELECT stripe_subscription_id FROM subscriptions
                WHERE lower(email) = lower($1) AND stripe_subscription_id IS NOT NULL
                  AND status = ANY($2::text[])""",
            email, list(_ACTIVE_SUB_STATUSES),
        )
        plan.stripe_subscriptions += [r["stripe_subscription_id"] for r in rows]
    plan.stripe_subscriptions = list(dict.fromkeys(plan.stripe_subscriptions))
    return plan


async def cancel_stripe_subscriptions(subscription_ids: list[str]) -> None:
    """Cancel immediately. Already-cancelled or missing subscriptions count as done."""
    if not subscription_ids:
        return
    import stripe

    if not stripe.api_key:
        raise BillingCancellationFailed("Billing is not configured on this server")
    for sub_id in subscription_ids:
        try:
            await asyncio.to_thread(stripe.Subscription.cancel, sub_id)
        except stripe.InvalidRequestError as exc:
            if getattr(exc, "code", None) == "resource_missing":
                continue
            # Stripe answers 400 for a subscription that is already cancelled.
            if "canceled" in str(exc).lower():
                continue
            log.warning("stripe cancel failed for %s", sub_id, exc_info=True)
            raise BillingCancellationFailed("Could not cancel your subscription") from exc
        except stripe.StripeError as exc:
            log.warning("stripe cancel failed for %s", sub_id, exc_info=True)
            raise BillingCancellationFailed("Could not cancel your subscription") from exc


async def apply_account_deletion(conn, user_id: str, email: str, plan: DeletionPlan) -> None:
    uid = uuid.UUID(user_id)
    async with conn.transaction():
        if plan.orgs_to_delete:
            await conn.execute(
                "UPDATE organizations SET deleted_at = NOW() WHERE id = ANY($1::uuid[])",
                plan.orgs_to_delete,
            )
            await conn.execute(
                """UPDATE org_subscriptions SET status = 'canceled', updated_at = NOW()
                    WHERE organization_id = ANY($1::uuid[]) AND status = ANY($2::text[])""",
                plan.orgs_to_delete, list(_ACTIVE_SUB_STATUSES),
            )
        if await conn.fetchval("SELECT to_regclass('subscriptions') IS NOT NULL"):
            await conn.execute(
                """UPDATE subscriptions SET status = 'canceled', updated_at = NOW()
                    WHERE lower(email) = lower($1) AND status = ANY($2::text[])""",
                email, list(_ACTIVE_SUB_STATUSES),
            )
        await conn.execute("DELETE FROM users WHERE id = $1", uid)
