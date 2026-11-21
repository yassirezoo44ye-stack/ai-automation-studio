# BYOK encryption key rotation

Use a dedicated BYOK_FERNET_KEY from a secure secret manager, never SESSION_SECRET.
BYOK_FERNET_PREVIOUS_KEYS is an optional comma-separated list of older Fernet keys
without spaces. All keys must be valid; invalid configuration fails closed.

To stage rotation, place the NEW key in BYOK_FERNET_KEY and the OLD key in
BYOK_FERNET_PREVIOUS_KEYS. New writes use the new key; reads accept both.
Old ciphertext is NOT automatically re-encrypted.

Do not remove old keys until a separately implemented, reviewed, backed-up
re-encryption migration has successfully verified every stored credential.
That migration is NOT implemented. Compromised provider keys must be revoked
and replaced; retaining an old encryption key is not incident remediation.

Never expose encryption keys to frontend or untrusted preview environments.
No production migration or API activation is performed by this branch.
