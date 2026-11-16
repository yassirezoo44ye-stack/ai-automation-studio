"""Privileged read-only final BYOK ciphertext verification.

Requires a trusted audit-only connection and a consistent database snapshot.
Never exposes ciphertext, plaintext or credential identifiers. This check is
advisory and cannot authorize removal of previous encryption keys.
"""
from __future__ import annotations
import os
from cryptography.fernet import Fernet, InvalidToken
from app.ai.user_credentials import _cipher

async def verify_all_primary_ciphertexts(conn) -> dict[str, int | bool]:
    _cipher()  # Fail closed on invalid encryption configuration.
    primary = Fernet(os.environ["BYOK_FERNET_KEY"].encode("ascii"))
    scanned = unreadable = 0
    async with conn.transaction(isolation="repeatable_read", readonly=True):
        rows = await conn.fetch("SELECT encrypted_key FROM ai_user_credentials")
        for row in rows:
            scanned += 1
            try:
                primary.decrypt(row["encrypted_key"].encode("ascii"))
            except (InvalidToken, ValueError, UnicodeError):
                unreadable += 1
    return {"scanned": scanned, "not_primary": unreadable,
            "complete": scanned > 0 and unreadable == 0}
