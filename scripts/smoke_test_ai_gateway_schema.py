"""
Smoke test for the AI Gateway schema fix (P0 in
docs/AI_ENTRY_POINT_UNIFICATION_AUDIT.md §8).

Proves, against a real database, that:
  1. init_ai_gateway_schema()/init_ai_usage_schema() run cleanly (idempotent
     — safe against both a fresh DB and one that already has these tables).
  2. A row can be inserted into ai_conversations.
  3. A row can be inserted into ai_usage_log referencing that conversation
     (ai_usage_log.conversation_id -> ai_conversations.id — the FK that was
     previously pointed at the wrong table, see app/ai/schema.py).
  4. The FK is actually enforced, not just present-but-toothless: inserting
     ai_usage_log with a conversation_id that doesn't exist in
     ai_conversations must fail with a foreign-key violation.

Schema-only scope, matching P0's boundary — this does not touch AIGateway,
routing, or any traffic path. Test rows are cleaned up on exit either way.

Requires DATABASE_URL to point at a reachable Postgres instance.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL must be set before running this check.", file=sys.stderr)
    sys.exit(1)


async def main() -> None:
    import asyncpg
    from app.ai.schema import init_ai_gateway_schema, init_ai_usage_schema

    conn = await asyncpg.connect(DATABASE_URL)
    conv_id: uuid.UUID | None = None
    try:
        # 1. Idempotent schema init — the exact functions factory.py calls.
        await init_ai_gateway_schema(conn)
        await init_ai_usage_schema(conn)
        print("[1/4] schema init: OK")

        # 2. Insert into ai_conversations.
        conv_id = await conn.fetchval(
            "INSERT INTO ai_conversations (user_id, title) VALUES (NULL, $1) RETURNING id",
            "smoke-test-conversation",
        )
        print(f"[2/4] ai_conversations insert: OK (id={conv_id})")

        # 3. Insert into ai_usage_log referencing that conversation — this is
        #    the exact write cost_tracker.record() performs.
        await conn.execute(
            """
            INSERT INTO ai_usage_log
              (user_id, conversation_id, provider, model, input_tokens,
               output_tokens, total_tokens, cost_usd)
            VALUES (NULL, $1, 'smoke-test', 'smoke-test', 1, 1, 2, 0.0)
            """,
            conv_id,
        )
        print("[3/4] ai_usage_log insert referencing ai_conversations: OK")

        # 4. FK must actually reject a conversation_id that doesn't exist.
        bogus_id = uuid.uuid4()
        try:
            await conn.execute(
                """
                INSERT INTO ai_usage_log
                  (user_id, conversation_id, provider, model, input_tokens,
                   output_tokens, total_tokens, cost_usd)
                VALUES (NULL, $1, 'smoke-test', 'smoke-test', 1, 1, 2, 0.0)
                """,
                bogus_id,
            )
        except asyncpg.ForeignKeyViolationError:
            print("[4/4] FK correctly rejects a non-existent conversation_id: OK")
        else:
            raise AssertionError(
                "ai_usage_log.conversation_id accepted a conversation_id "
                f"({bogus_id}) that does not exist in ai_conversations — "
                "the FK is not actually enforcing."
            )

        print("SMOKE TEST PASSED")
    except Exception as exc:
        print(f"SMOKE TEST FAILED: {exc!r}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up test data regardless of outcome — this may run against a
        # shared local dev database, not a disposable one.
        await conn.execute("DELETE FROM ai_usage_log WHERE provider = 'smoke-test'")
        if conv_id is not None:
            await conn.execute("DELETE FROM ai_conversations WHERE id = $1", conv_id)
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
