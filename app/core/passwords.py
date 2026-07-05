"""Password hashing with bcrypt + SHA-256 prehash.

bcrypt truncates input at 72 bytes, which breaks Unicode-heavy passwords
(Arabic, Chinese, etc. where each char is 2-4 bytes in UTF-8).
Prehashing with SHA-256 produces a fixed 44-char base64 string that is
always well under the 72-byte limit, while preserving the full entropy
of the original password.
"""
import base64
import hashlib

from passlib.context import CryptContext

_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _prehash(plain: str) -> str:
    digest = hashlib.sha256(plain.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def hash_password(plain: str) -> str:
    return _ctx.hash(_prehash(plain))


def verify_password(plain: str, hashed: str) -> bool:
    return _ctx.verify(_prehash(plain), hashed)
