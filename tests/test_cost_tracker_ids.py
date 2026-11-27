"""cost_tracker.record accepts ids as strings or as UUID objects.

Regression: the AI gateway passes ids read back from asyncpg, and
uuid.UUID(<asyncpg UUID>) raised "'UUID' object has no attribute 'replace'",
so every usage row from the gateway was silently dropped.
"""
import asyncio
import uuid

from app.ai import cost_tracker
from app.ai.models import UsageStats


class _UUIDLike:
    """Stands in for asyncpg's UUID: not a str, str() gives the canonical form."""
    def __init__(self, u: uuid.UUID):
        self._u = u

    def __str__(self) -> str:
        return str(self._u)


class _Conn:
    def __init__(self):
        self.args = None

    async def execute(self, _sql, *args):
        self.args = args


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


def _stats() -> UsageStats:
    return UsageStats(provider="anthropic", model="m", input_tokens=3, output_tokens=4, total_tokens=7, cost_usd=0.01)


def test_record_accepts_uuid_objects_from_the_database():
    user, org, conv = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    pool = _Pool()
    asyncio.run(cost_tracker.record(
        pool=pool, user_id=_UUIDLike(user), org_id=org, conversation_id=str(conv), stats=_stats(),
    ))
    assert pool.conn.args is not None, "usage row was not written"
    assert pool.conn.args[:3] == (user, org, conv)


def test_record_still_accepts_plain_strings_and_none():
    user = uuid.uuid4()
    pool = _Pool()
    asyncio.run(cost_tracker.record(pool=pool, user_id=str(user), org_id=None, conversation_id=None, stats=_stats()))
    assert pool.conn.args[:3] == (user, None, None)
