"""Password hashing using bcrypt directly (bypasses passlib's bcrypt 4.x incompatibility).

SHA-256 prehash keeps passwords under bcrypt's 72-byte limit, which is
critical for Unicode passwords (Arabic, etc.) where chars are multi-byte.
"""
import hashlib

import bcrypt


def _prehash(plain: str) -> bytes:
    return hashlib.sha256(plain.encode("utf-8")).digest()  # always 32 bytes


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prehash(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))
