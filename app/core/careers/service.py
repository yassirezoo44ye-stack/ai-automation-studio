import asyncio
import hashlib
import json
import logging
import uuid

from . import gmail
from .engine import assess, draft_application, parse_alert
from .models import CareerProfile

log = logging.getLogger(__name__)


def value(data):
    return json.loads(data) if isinstance(data, str) else data


class CareerService:
    def __init__(self, pool):
        self.pool = pool

    @staticmethod
    def owner(ctx):
        return uuid.UUID(ctx.org_id), uuid.UUID(ctx.user_id)

    async def profile(self, ctx):
        async with self.pool.acquire() as conn:
            data = await conn.fetchval(
                "SELECT profile FROM career_profiles WHERE organization_id=$1 AND user_id=$2",
                *self.owner(ctx),
            )
        return CareerProfile.model_validate(value(data) if data else {})

    async def save_profile(self, ctx, profile):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO career_profiles (organization_id,user_id,profile) VALUES ($1,$2,$3::jsonb)
                ON CONFLICT (organization_id,user_id) DO UPDATE SET profile=EXCLUDED.profile,updated_at=now()""",
                *self.owner(ctx),
                profile.model_dump_json(),
            )
        return profile

    async def import_on(self, conn, ctx, text, source="manual", received_at=None):
        jobs, inserted = parse_alert(text, source), 0
        for job in jobs:
            job["source_received_at"] = received_at
            result = await conn.fetchval(
                """INSERT INTO career_jobs (organization_id,user_id,job_key,data)
                VALUES ($1,$2,$3,$4::jsonb) ON CONFLICT (organization_id,user_id,job_key) DO NOTHING RETURNING id""",
                *self.owner(ctx),
                job["key"],
                json.dumps(job),
            )
            inserted += result is not None
        return {
            "found": len(jobs),
            "inserted": inserted,
            "duplicates": len(jobs) - inserted,
            "warning": None
            if jobs
            else "No supported direct job links found / لم توجد روابط وظائف مباشرة مدعومة",
        }

    async def import_alert(self, ctx, body):
        async with self.pool.acquire() as conn, conn.transaction():
            return await self.import_on(conn, ctx, body.text, body.source)

    async def jobs(self, ctx):
        profile = await self.profile(ctx)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id,data,status,created_at FROM career_jobs WHERE organization_id=$1 AND user_id=$2 ORDER BY created_at DESC LIMIT 500",
                *self.owner(ctx),
            )
        items = [
            {
                **value(row["data"]),
                "id": str(row["id"]),
                "status": row["status"],
                "created_at": row["created_at"].isoformat(),
                "assessment": assess(value(row["data"]), profile),
            }
            for row in rows
        ]
        return sorted(
            items,
            key=lambda x: (
                x["assessment"]["expired"],
                -x["assessment"]["score"],
                -(x["salary"].get("min") or 0)
                if x["salary"].get("period") == "monthly"
                and x["salary"].get("kind") == "listed_unverified"
                else 0,
            ),
        )

    async def status(self, ctx, job_id, status):
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "UPDATE career_jobs SET status=$4,updated_at=now() WHERE organization_id=$1 AND user_id=$2 AND id=$3 RETURNING id",
                *self.owner(ctx),
                job_id,
                status,
            )

    async def job(self, ctx, job_id):
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT data FROM career_jobs WHERE organization_id=$1 AND user_id=$2 AND id=$3",
                *self.owner(ctx),
                job_id,
            )
        return value(result) if result else None

    async def draft(self, ctx, job_id):
        job = await self.job(ctx, job_id)
        return draft_application(job, await self.profile(ctx)) if job else None

    async def oauth_begin(self, ctx):
        state, verifier, url = gmail.authorization()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM career_oauth_states WHERE expires_at < now()"
            )
            await conn.execute(
                """INSERT INTO career_oauth_states (state_hash,organization_id,user_id,verifier_encrypted,expires_at)
                VALUES ($1,$2,$3,$4,now()+interval '10 minutes')""",
                hashlib.sha256(state.encode()).hexdigest(),
                *self.owner(ctx),
                gmail.cipher().encrypt(verifier.encode()).decode(),
            )
        return {"url": url}

    async def oauth_finish(self, ctx, body):
        async with self.pool.acquire() as conn:
            state = await conn.fetchval(
                """DELETE FROM career_oauth_states WHERE state_hash=$1 AND organization_id=$2 AND user_id=$3
                AND expires_at>now() RETURNING verifier_encrypted""",
                hashlib.sha256(body.state.encode()).hexdigest(),
                *self.owner(ctx),
            )
            if state is None:
                raise ValueError(
                    "Invalid or expired OAuth state / جلسة الربط غير صالحة أو منتهية"
                )
            refresh = await gmail.exchange(body.code, gmail.decrypt(state))
            await conn.execute(
                """INSERT INTO career_gmail (organization_id,user_id,refresh_encrypted) VALUES ($1,$2,$3)
                ON CONFLICT (organization_id,user_id) DO UPDATE SET refresh_encrypted=EXCLUDED.refresh_encrypted,last_error=NULL""",
                *self.owner(ctx),
                gmail.cipher().encrypt(refresh.encode()).decode(),
            )

    async def connection(self, ctx):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT enabled,interval_hours,last_sync,last_error FROM career_gmail WHERE organization_id=$1 AND user_id=$2",
                *self.owner(ctx),
            )
        try:
            gmail.settings()
            configured = True
        except gmail.GmailUnavailable:
            configured = False
        return {
            "configured": configured,
            "connected": bool(row),
            "enabled": row["enabled"] if row else False,
            "interval_hours": row["interval_hours"] if row else 24,
            "last_sync": row["last_sync"].isoformat()
            if row and row["last_sync"]
            else None,
            "last_error": row["last_error"] if row else None,
        }

    async def schedule(self, ctx, body):
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                """UPDATE career_gmail SET enabled=$3,interval_hours=$4,next_sync=now()
                WHERE organization_id=$1 AND user_id=$2 RETURNING user_id""",
                *self.owner(ctx),
                body.enabled,
                body.interval_hours,
            )
        if not result:
            raise ValueError("Connect Gmail first / اربط Gmail أولًا")

    async def disconnect(self, ctx):
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                "career:" + ctx.org_id + ":" + ctx.user_id,
            )
            for table in (
                "career_gmail",
                "career_oauth_states",
                "career_gmail_messages",
            ):
                await conn.execute(
                    f"DELETE FROM {table} WHERE organization_id=$1 AND user_id=$2",
                    *self.owner(ctx),
                )

    async def sync(self, ctx, *, scheduled=False):
        inserted, found, unparsed = 0, 0, 0
        async with self.pool.acquire() as conn:
            lock_name = "career:" + ctx.org_id + ":" + ctx.user_id
            locked = await conn.fetchval(
                "SELECT pg_try_advisory_lock(hashtextextended($1,0))", lock_name
            )
            if not locked:
                return {"busy": True, "inserted": 0}
            try:
                row = await conn.fetchrow(
                    "SELECT refresh_encrypted,enabled,next_sync<=now() AS due FROM career_gmail WHERE organization_id=$1 AND user_id=$2",
                    *self.owner(ctx),
                )
                if not row:
                    raise ValueError("Connect Gmail first / اربط Gmail أولًا")
                if scheduled and (not row["enabled"] or not row["due"]):
                    return {"busy": False, "inserted": 0}
                processed = await conn.fetch(
                    "SELECT message_id FROM career_gmail_messages WHERE organization_id=$1 AND user_id=$2",
                    *self.owner(ctx),
                )
                # Flatten records to provider IDs.
                processed_ids = {r[0] for r in processed}
                try:
                    alerts = await asyncio.wait_for(
                        gmail.read_alerts(
                            gmail.decrypt(row["refresh_encrypted"]), processed_ids
                        ),
                        timeout=90,
                    )
                except TimeoutError:
                    raise gmail.GmailUnavailable(
                        "Gmail sync timed out; retry / انتهت مهلة المزامنة؛ أعد المحاولة"
                    ) from None
                for mid, text, received_at in alerts:
                    async with conn.transaction():
                        result = await self.import_on(
                            conn, ctx, text, "manual", received_at
                        )
                        await conn.execute(
                            "INSERT INTO career_gmail_messages (organization_id,user_id,message_id) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                            *self.owner(ctx),
                            mid,
                        )
                    inserted += result["inserted"]
                    found += result["found"]
                    unparsed += result["found"] == 0
                await conn.execute(
                    """UPDATE career_gmail SET last_sync=now(),last_error=NULL,next_sync=now()+interval_hours*interval '1 hour'
                    WHERE organization_id=$1 AND user_id=$2""",
                    *self.owner(ctx),
                )
            except gmail.GmailUnavailable as exc:
                await conn.execute(
                    """UPDATE career_gmail SET last_error=$3,next_sync=now()+interval '1 hour'
                    WHERE organization_id=$1 AND user_id=$2""",
                    *self.owner(ctx),
                    str(exc),
                )
                raise
            finally:
                await conn.execute(
                    "SELECT pg_advisory_unlock(hashtextextended($1,0))", lock_name
                )
        if inserted:
            try:
                from app.core.notifications import get_notification_service

                await get_notification_service().create(
                    user_id=ctx.user_id,
                    organization_id=ctx.org_id,
                    type_="career.jobs_imported",
                    title="New job alerts / وظائف جديدة",
                    message=f"{inserted} new jobs ready to review / وظائف جديدة جاهزة للمراجعة",
                    action={"label": "Career assistant", "href": "/careers"},
                )
            except Exception:  # noqa: BLE001 — isolate background failures without logging private data
                log.warning("Career notification unavailable", exc_info=False)
        return {
            "messages": len(alerts),
            "found": found,
            "inserted": inserted,
            "unparsed_messages": unparsed,
            "busy": False,
        }


async def scheduler(pool):
    """DB due times and per-owner advisory locks coordinate multiple web workers."""
    from app.tenancy.context import OrgContext

    while True:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""SELECT c.organization_id,c.user_id FROM career_gmail c
                    JOIN organizations o ON o.id=c.organization_id AND o.deleted_at IS NULL
                    JOIN organization_members m ON m.organization_id=c.organization_id AND m.user_id=c.user_id AND m.deleted_at IS NULL
                    WHERE c.enabled AND c.next_sync<=now() LIMIT 20""")
            for row in rows:
                ctx = OrgContext(
                    str(row["organization_id"]), str(row["user_id"]), "", "member"
                )
                try:
                    await CareerService(pool).sync(ctx, scheduled=True)
                except Exception:  # noqa: BLE001 — isolate background failures without logging private data
                    log.warning("Career scheduled sync unavailable", exc_info=False)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — isolate background failures without logging private data
            log.warning("Career scheduler tick unavailable", exc_info=False)
        await asyncio.sleep(60)
