"""
Plugin code signing — Ed25519 signature verification for plugin bundles.

Uses the `cryptography` library already installed in this codebase for
Fernet secret encryption elsewhere (app/plugins/secrets.py,
app/integrations/credential_store.py) — no new dependency.

Signing is advisory, not mandatory, this phase: a bundle with no
signature/public_key loads with a logged warning (matching
app/marketplace/security.py's scan_for_malware/scan_dependency_vulnerabilities
"stub hooks that only warn" precedent for this same reason — the platform
doesn't yet require every publisher to sign). A bundle that DOES declare a
signature must verify correctly or the load is rejected outright — once a
publisher opts in to signing, a broken/forged signature is always fatal,
never silently ignored.

Not wired to marketplace_publishers' verified-publisher trust chain this
phase — a valid signature only proves "signed by whoever holds this
specific private key," not "signed by a platform-verified publisher."
Linking a signing key to a verified publisher record is a reasonable
follow-up, not built here to keep this phase's scope to what was asked.
"""
from __future__ import annotations

import base64
import logging

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

log = logging.getLogger(__name__)


class SignatureVerificationError(Exception):
    pass


def generate_keypair() -> tuple[str, str]:
    """Returns (private_key_pem, public_key_pem) for a publisher's own
    one-time key generation. The platform never generates or stores a
    private key on a publisher's behalf — this is a convenience for local
    key creation, callable from a script or a future CLI command."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def sign_code(code: str, private_key_pem: str) -> str:
    """Returns a base64-encoded Ed25519 signature over the UTF-8 plugin
    source. A publisher-side operation — the loader never calls this, only
    verify_signature()."""
    private_key = load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SignatureVerificationError("private key is not Ed25519")
    signature = private_key.sign(code.encode("utf-8"))
    return base64.b64encode(signature).decode("ascii")


def verify_signature(code: str, signature_b64: str, public_key_pem: str) -> bool:
    """True iff `signature_b64` is a valid Ed25519 signature over `code` by
    the holder of `public_key_pem`. Never raises — any malformed input (bad
    base64, wrong key type, corrupted PEM) is a failed verification, not an
    exception the caller has to catch separately from a genuine mismatch."""
    try:
        public_key = load_pem_public_key(public_key_pem.encode("utf-8"))
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        signature = base64.b64decode(signature_b64, validate=True)
        public_key.verify(signature, code.encode("utf-8"))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
