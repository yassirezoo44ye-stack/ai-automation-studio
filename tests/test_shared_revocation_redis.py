"""Cross-process HTTP authorization with an actual, disposable local Redis."""
import json
import os
import subprocess
import sys
import uuid
from urllib.parse import urlparse

import pytest


def local_environment():
    url = os.getenv("LOCAL_SECURITY_REDIS_URL")
    if not url:
        pytest.skip("Disposable local Redis required")
    if urlparse(url).hostname not in {"localhost", "127.0.0.1"}:
        pytest.fail("Refusing a non-local Redis for this test")
    return {**os.environ, "REDIS_URL": url, "PYTHONPATH": "."}


def process(code, env, data=None):
    result = subprocess.run([sys.executable, "-c", code], input=json.dumps(data), text=True,
                            capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_revocation_enforced_in_an_independent_http_worker():
    env = local_environment()
    uid = str(uuid.uuid4())
    # Worker A issues a token and revokes the account in the actual Redis store.
    issued = process('''
import asyncio,json,sys,time,jwt
from app.core.jwt_utils import revoke_user_tokens
from app.core.config import SESSION_SECRET
uid=json.load(sys.stdin)
token=jwt.encode({"sub":uid,"email":"local@example.com","type":"access","iat":time.time()-60,"exp":time.time()+240},SESSION_SECRET,algorithm="HS256")
asyncio.run(revoke_user_tokens(uid))
print(json.dumps({"token":token,"uid":uid}))
''', env, uid)
    data = json.loads(issued.strip().splitlines()[-1])
    # Worker B has no local revocation map; HTTP middleware must consult Redis.
    checked = process('''
import asyncio,json,sys,httpx
from app.factory import create_app
from app.core.jwt_utils import make_access_token
from app.core.cache import get_redis
async def main():
    data=json.load(sys.stdin)
    assert (await get_redis()).backend == "redis"
    app=create_app()
    @app.post("/api/local-revocation-probe")
    async def probe(): return {"ok":True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://localhost") as client:
        old=await client.post("/api/local-revocation-probe",headers={"Authorization":"Bearer "+data["token"]})
        new=await client.post("/api/local-revocation-probe",headers={"Authorization":"Bearer "+make_access_token(data["uid"],"local@example.com")})
        assert old.status_code == 401
        assert new.status_code == 200
        print("INDEPENDENT_WORKER_REVOKED_OLD_ACCEPTED_NEW")
asyncio.run(main())
''', env, data)
    assert "INDEPENDENT_WORKER_REVOKED_OLD_ACCEPTED_NEW" in checked


def test_configured_redis_failure_does_not_accept_local_fallback():
    env = local_environment()
    # Port 1 on loopback has no Redis. No external address or real key is used.
    env["REDIS_URL"] = "redis://127.0.0.1:1/0"
    checked = process('''
import asyncio,httpx
from app.factory import create_app
from app.core.jwt_utils import make_access_token
async def main():
    app=create_app()
    @app.post("/api/local-revocation-probe")
    async def probe(): return {"ok":True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://localhost") as client:
        response=await client.post("/api/local-revocation-probe",headers={"Authorization":"Bearer "+make_access_token("local-redis-outage","local@example.com")})
        assert response.status_code == 503
        print("UNAVAILABLE_REDIS_DENIED")
asyncio.run(main())
''', env)
    assert "UNAVAILABLE_REDIS_DENIED" in checked


class LostRevocationSecurityFailure(AssertionError):
    """The known unsafe acceptance, distinct from setup/connection failures."""


@pytest.mark.xfail(strict=True, raises=LostRevocationSecurityFailure,
                   reason="Redis revocation loss requires a durable auth authority; blocks activation")
def test_lost_revocation_record_must_not_restore_an_old_token():
    """Known security gap: erase only this synthetic user's Redis record."""
    env = local_environment()
    uid = str(uuid.uuid4())
    issued = process('''
import asyncio,json,sys,time,jwt
from app.core.jwt_utils import revoke_user_tokens
from app.core.config import SESSION_SECRET
from app.core.cache import get_redis
async def main():
    uid=json.load(sys.stdin)
    token=jwt.encode({"sub":uid,"email":"local@example.com","type":"access","iat":time.time()-60,"exp":time.time()+240},SESSION_SECRET,algorithm="HS256")
    await revoke_user_tokens(uid)
    await (await get_redis()).delete("jwt:revoke:"+uid)
    print(json.dumps({"token":token}))
asyncio.run(main())
''', env, uid)
    data = json.loads(issued.strip().splitlines()[-1])
    observed = process('''
import asyncio,json,sys,jwt
from app.core.jwt_utils import verify_access_token
async def main():
    data=json.load(sys.stdin)
    try:
        await verify_access_token(data["token"])
    except jwt.PyJWTError:
        print("REJECTED_AFTER_LOSS")
        return
    print("ACCEPTED_AFTER_LOSS")
asyncio.run(main())
''', env, data)

    if "ACCEPTED_AFTER_LOSS" in observed:
        raise LostRevocationSecurityFailure("Old JWT accepted after losing its shared revocation record")
    assert "REJECTED_AFTER_LOSS" in observed
