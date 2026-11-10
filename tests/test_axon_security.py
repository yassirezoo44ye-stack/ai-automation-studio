"""Unit tests for app/core/axon_security.py (no database needed)."""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import pytest

from app.core import axon_security as sec
from app.core.config import settings

UID, TID, SID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


# ── key derivation ───────────────────────────────────────────────────────────

def test_derived_keys_are_distinct_and_stable():
    a = sec.derive_key(sec.PURPOSE_ACCESS_TOKEN)
    b = sec.derive_key(sec.PURPOSE_REFRESH_TOKEN)
    c = sec.derive_key(sec.PURPOSE_API_KEY)
    assert len({a, b, c}) == 3
    assert a == sec.derive_key(sec.PURPOSE_ACCESS_TOKEN)
    assert settings.session_secret.get_secret_value().encode()[:32] not in {a, b, c}


def test_derive_key_requires_namespace():
    with pytest.raises(ValueError):
        sec.derive_key("jwt")


# ── passwords ────────────────────────────────────────────────────────────────

def test_hash_and_verify_round_trip():
    h = sec.hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert sec.verify_password("correct horse battery staple", h)
    assert not sec.verify_password("correct horse battery stapl", h)


def test_each_hash_is_salted():
    assert sec.hash_password("same password here") != sec.hash_password("same password here")


def test_arabic_password_and_nfkc_normalisation():
    pw = "كلمة سر قوية جداً ٢٠٢٦"
    h = sec.hash_password(pw)
    assert sec.verify_password(pw, h)
    # Full-width digits normalise to ASCII digits under NFKC.
    h2 = sec.hash_password("abcdefgh１２３４")
    assert sec.verify_password("abcdefgh1234", h2)


def test_verify_without_hash_is_false():
    assert sec.verify_password("anything at all", None) is False
    assert sec.verify_password("anything at all", "") is False


def test_verify_garbage_hash_is_false():
    assert sec.verify_password("anything at all", "not-a-hash") is False


def test_oversized_password_rejected_without_error():
    h = sec.hash_password("a reasonable password")
    assert sec.verify_password("x" * 100_000, h) is False
    with pytest.raises(sec.PasswordPolicyError):
        sec.hash_password("x" * (sec.PASSWORD_MAX_LENGTH + 1))


def test_legacy_bcrypt_hash_verifies_and_needs_rehash():
    legacy = bcrypt.hashpw(hashlib.sha256(b"old password 123").digest(), bcrypt.gensalt()).decode()
    assert sec.verify_password("old password 123", legacy)
    assert not sec.verify_password("wrong", legacy)
    assert sec.password_needs_rehash(legacy)


def test_current_hash_does_not_need_rehash():
    assert not sec.password_needs_rehash(sec.hash_password("fresh password 1"))


@pytest.mark.parametrize("pw, reason", [
    ("short1", "at least"),
    ("password123", "too common"),
    ("aaaaaaaaaaaaaa", "different characters"),
    (" leading space pw", "whitespace"),
    ("has\x00control chars", "control"),
])
def test_password_policy_rejects(pw, reason):
    with pytest.raises(sec.PasswordPolicyError) as exc:
        sec.validate_password(pw)
    assert any(reason in r for r in exc.value.reasons)


def test_password_policy_rejects_email_name():
    with pytest.raises(sec.PasswordPolicyError):
        sec.validate_password("yassir-is-great-2026", email="yassir@example.com")


def test_password_policy_accepts_good_password():
    sec.validate_password("Tr0ub4dor & horse battery", email="someone@example.com")


# ── access tokens ────────────────────────────────────────────────────────────

def _issue(**kw):
    return sec.issue_access_token(user_id=UID, tenant_id=TID, session_id=SID,
                                  scopes={"workflows:read", "agents:execute"}, **kw)


def test_access_token_round_trip():
    token, exp = _issue()
    claims = sec.decode_access_token(token)
    assert (claims.user_id, claims.tenant_id, claims.session_id) == (UID, TID, SID)
    assert claims.scopes == frozenset({"workflows:read", "agents:execute"})
    assert claims.expires_at == exp
    assert exp - claims.issued_at == timedelta(seconds=settings.auth_access_ttl_s)


def test_access_token_expired():
    token, _ = _issue(now=datetime.now(timezone.utc) - timedelta(hours=2))
    with pytest.raises(sec.TokenError, match="expired"):
        sec.decode_access_token(token)


def test_access_token_tampered_payload():
    token, _ = _issue()
    head, body, sig = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "=="))
    payload["tid"] = str(uuid.uuid4())
    forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(sec.TokenError):
        sec.decode_access_token(f"{head}.{forged}.{sig}")


def test_access_token_wrong_key():
    payload = jwt.decode(_issue()[0], options={"verify_signature": False})
    forged = jwt.encode(payload, b"k" * 32, algorithm="HS256", headers={"kid": "v1"})
    with pytest.raises(sec.TokenError):
        sec.decode_access_token(forged)


def test_access_token_alg_none_rejected():
    payload = jwt.decode(_issue()[0], options={"verify_signature": False})
    unsigned = jwt.encode(payload, None, algorithm="none", headers={"kid": "v1"})
    with pytest.raises(sec.TokenError):
        sec.decode_access_token(unsigned)


def test_access_token_signed_with_raw_session_secret_rejected():
    # The legacy jwt_utils tokens are signed with SESSION_SECRET itself; they
    # must never be accepted as Axon access tokens.
    payload = jwt.decode(_issue()[0], options={"verify_signature": False})
    legacy = jwt.encode(payload, settings.session_secret.get_secret_value(), algorithm="HS256",
                        headers={"kid": "v1"})
    with pytest.raises(sec.TokenError):
        sec.decode_access_token(legacy)


@pytest.mark.parametrize("claim", ["sid", "tid", "jti", "typ", "aud", "iss"])
def test_access_token_missing_claim(claim):
    payload = jwt.decode(_issue()[0], options={"verify_signature": False})
    del payload[claim]
    token = jwt.encode(payload, sec.derive_key(sec.PURPOSE_ACCESS_TOKEN), algorithm="HS256", headers={"kid": "v1"})
    with pytest.raises(sec.TokenError):
        sec.decode_access_token(token)


def test_access_token_wrong_type_or_audience():
    key = sec.derive_key(sec.PURPOSE_ACCESS_TOKEN)
    payload = jwt.decode(_issue()[0], options={"verify_signature": False})
    for change in ({"typ": "refresh"}, {"aud": "someone-else"}, {"iss": "evil"}):
        bad = jwt.encode({**payload, **change}, key, algorithm="HS256", headers={"kid": "v1"})
        with pytest.raises(sec.TokenError):
            sec.decode_access_token(bad)


def test_access_token_unknown_kid():
    payload = jwt.decode(_issue()[0], options={"verify_signature": False})
    bad = jwt.encode(payload, sec.derive_key(sec.PURPOSE_ACCESS_TOKEN), algorithm="HS256", headers={"kid": "v0"})
    with pytest.raises(sec.TokenError):
        sec.decode_access_token(bad)


@pytest.mark.parametrize("junk", ["", "abc", "a.b.c", "x" * 5000, None, 42])
def test_access_token_garbage(junk):
    with pytest.raises(sec.TokenError):
        sec.decode_access_token(junk)


# ── refresh tokens ───────────────────────────────────────────────────────────

def test_refresh_token_digest():
    token, digest = sec.new_refresh_token()
    assert token.startswith("axr_") and len(digest) == 32
    assert sec.hash_refresh_token(token) == digest
    other, other_digest = sec.new_refresh_token()
    assert other != token and other_digest != digest


@pytest.mark.parametrize("junk", ["", "axr_short", "axk_" + "a" * 43, "axr_" + "a" * 42 + "!", None])
def test_refresh_token_malformed(junk):
    with pytest.raises(sec.TokenError):
        sec.hash_refresh_token(junk)


# ── API keys ─────────────────────────────────────────────────────────────────

def test_api_key_generation_and_match():
    k = sec.generate_api_key()
    assert len(k.prefix) == 16 and k.prefix.startswith("axk_")
    assert k.plaintext.startswith(k.prefix + "_")
    assert sec.parse_api_key(k.plaintext) == k.prefix
    assert sec.api_key_matches(k.plaintext, k.digest)
    assert k.plaintext not in repr(k)


def test_api_key_hex_digest_fits_varchar():
    k = sec.generate_api_key()
    assert sec.hash_api_key_hex(k.plaintext) == k.digest.hex()
    assert len(k.digest.hex()) == 64


def test_api_key_one_char_off_does_not_match():
    k = sec.generate_api_key()
    flipped = k.plaintext[:-1] + ("A" if k.plaintext[-1] != "A" else "B")
    assert not sec.api_key_matches(flipped, k.digest)


@pytest.mark.parametrize("junk", ["", "axk_", "axon_abc", "axk_short_secret", None, "axk_" + "a" * 12 + "_" + "b" * 42])
def test_api_key_malformed(junk):
    with pytest.raises(sec.ApiKeyFormatError):
        sec.parse_api_key(junk)
    assert sec.api_key_matches(junk, b"\0" * 32) is False


# ── webhook signatures ───────────────────────────────────────────────────────

SECRET = "whsec_test_secret_value"
BODY = b'{"event":"lead.created","id":1}'
DELIVERY = "dlv_0123456789"


def test_webhook_round_trip():
    now = time.time()
    header = sec.sign_webhook(SECRET, delivery_id=DELIVERY, body=BODY, timestamp=int(now))
    assert sec.verify_webhook_signature(SECRET, header=header, delivery_id=DELIVERY, body=BODY, now=now) == int(now)


def test_webhook_tampered_body_or_delivery():
    now = time.time()
    header = sec.sign_webhook(SECRET, delivery_id=DELIVERY, body=BODY, timestamp=int(now))
    with pytest.raises(sec.WebhookVerificationError):
        sec.verify_webhook_signature(SECRET, header=header, delivery_id=DELIVERY, body=BODY + b" ", now=now)
    with pytest.raises(sec.WebhookVerificationError):
        sec.verify_webhook_signature(SECRET, header=header, delivery_id="dlv_9999999999", body=BODY, now=now)


def test_webhook_wrong_secret():
    now = time.time()
    header = sec.sign_webhook("whsec_other", delivery_id=DELIVERY, body=BODY, timestamp=int(now))
    with pytest.raises(sec.WebhookVerificationError, match="mismatch"):
        sec.verify_webhook_signature(SECRET, header=header, delivery_id=DELIVERY, body=BODY, now=now)


def test_webhook_stale_and_future_timestamps():
    now = time.time()
    for skew in (-301, 301):
        header = sec.sign_webhook(SECRET, delivery_id=DELIVERY, body=BODY, timestamp=int(now + skew))
        with pytest.raises(sec.WebhookVerificationError, match="tolerance"):
            sec.verify_webhook_signature(SECRET, header=header, delivery_id=DELIVERY, body=BODY, now=now)


def test_webhook_rotation_accepts_old_or_new_secret():
    now = time.time()
    old = sec.sign_webhook("whsec_old", delivery_id=DELIVERY, body=BODY, timestamp=int(now))
    new = sec.sign_webhook("whsec_new", delivery_id=DELIVERY, body=BODY, timestamp=int(now))
    for header in (old, new):
        sec.verify_webhook_signature(["whsec_new", "whsec_old"], header=header, delivery_id=DELIVERY,
                                     body=BODY, now=now)
    # Header carrying several v1 values: one valid is enough.
    t = int(now)
    multi = f"t={t},v1={'0' * 64},v1={new.split('v1=')[1]}"
    sec.verify_webhook_signature("whsec_new", header=multi, delivery_id=DELIVERY, body=BODY, now=now)


@pytest.mark.parametrize("header", [
    "", "garbage", "t=123", "v1=" + "a" * 64, "t=abc,v1=" + "a" * 64, "t=1,t=2,v1=" + "a" * 64,
    "t=1,v1=xyz", "t=1," + ",".join(["v1=" + "a" * 64] * 6), "t=1,v1=" + "a" * 2000,
])
def test_webhook_malformed_headers(header):
    with pytest.raises(sec.WebhookVerificationError):
        sec.verify_webhook_signature(SECRET, header=header, delivery_id=DELIVERY, body=BODY, now=1.0)


def test_webhook_unknown_scheme_is_not_trusted():
    now = time.time()
    good = sec.sign_webhook(SECRET, delivery_id=DELIVERY, body=BODY, timestamp=int(now))
    v0_only = good.replace("v1=", "v0=")
    with pytest.raises(sec.WebhookVerificationError):
        sec.verify_webhook_signature(SECRET, header=v0_only, delivery_id=DELIVERY, body=BODY, now=now)


@pytest.mark.parametrize("delivery", ["", "short", "has space here", "x" * 129])
def test_webhook_bad_delivery_id(delivery):
    with pytest.raises(sec.WebhookVerificationError):
        sec.verify_webhook_signature(SECRET, header="t=1,v1=" + "a" * 64, delivery_id=delivery, body=BODY, now=1.0)


def test_webhook_secret_format():
    s = sec.generate_webhook_secret()
    assert s.startswith("whsec_") and len(s) > 40
