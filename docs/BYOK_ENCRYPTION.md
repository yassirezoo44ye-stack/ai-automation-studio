# BYOK encryption-key requirements

BYOK uses a dedicated `BYOK_FERNET_KEY`, never `SESSION_SECRET`.
Generate a Fernet key in a secure administrator-controlled environment
and store it in a managed secret store. Do not commit or print it.
If missing or malformed, BYOK vault operations fail closed.

**Key rotation is not yet implemented.** Do not replace a live key until
a reviewed dual-key decrypt / re-encrypt migration and backup procedure
exists. This branch does not read or write live credentials.

The secret must not be copied to frontend environment variables or to
untrusted Vercel preview builds. BYOK routes remain disabled.
