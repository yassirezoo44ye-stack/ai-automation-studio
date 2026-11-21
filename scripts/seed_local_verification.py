"""Idempotent synthetic records in the disposable local verification DB only.

Requires LOCAL_SECURITY_TEST_DATABASE_URL and LOCAL_FLOW_PASSWORD. No mail,
AI, payments, remote credentials or production connection are used.
"""
import asyncio
import os
import uuid
from urllib.parse import urlparse

import asyncpg

from app.core.passwords import hash_password


async def main():
    dsn = os.environ["LOCAL_SECURITY_TEST_DATABASE_URL"]
    parsed = urlparse(dsn)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/flow_integration":
        raise SystemExit("Refusing a database other than the dedicated local integration DB")
    password = os.environ["LOCAL_FLOW_PASSWORD"]
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters for the local-only password")
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            for actor in ("owner", "other"):
                uid = uuid.uuid5(uuid.NAMESPACE_URL, f"flow-local-verification-user-{actor}")
                oid = uuid.uuid5(uuid.NAMESPACE_URL, f"flow-local-verification-org-{actor}")
                pid = uuid.uuid5(uuid.NAMESPACE_URL, f"flow-local-verification-project-{actor}")
                email = f"flow-local-{actor}@example.com"
                await conn.execute("INSERT INTO users(id,email,name,password_hash,email_verified) VALUES($1,$2,$3,$4,true) ON CONFLICT(id) DO NOTHING", uid,email,f"Flow local {actor}",hash_password(password))
                await conn.execute("INSERT INTO organizations(id,name,slug,created_by) VALUES($1,$2,$3,$4) ON CONFLICT(id) DO NOTHING",oid,f"Local verification {actor}",f"flow-local-verification-{actor}",uid)
                await conn.execute("INSERT INTO organization_members(organization_id,user_id,role) VALUES($1,$2,'owner') ON CONFLICT(organization_id,user_id) DO NOTHING",oid,uid)
                await conn.execute("INSERT INTO projects(id,user_id,name,description) VALUES($1,$2,$3,$4) ON CONFLICT(id) DO NOTHING",pid,uid,f"مشروع تحقق محلي — {actor}","Synthetic records persisted in PostgreSQL; no AI generation performed")
                for index in range(3):
                    lid = uuid.uuid5(uuid.NAMESPACE_URL, f"flow-local-verification-lead-{actor}-{index}")
                    await conn.execute("INSERT INTO leads(id,organization_id,name,email,source,status) VALUES($1,$2,$3,$4,'local-verification','new') ON CONFLICT(id) DO NOTHING",lid,oid,f"عميل اختبار محلي {index+1}",f"flow-local-lead-{actor}-{index}@example.com")
        print("Seeded 2 local test users, 2 organizations, 2 projects and 6 leads.")
        print("Local sign-in: flow-local-owner@example.com (password from LOCAL_FLOW_PASSWORD).")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
