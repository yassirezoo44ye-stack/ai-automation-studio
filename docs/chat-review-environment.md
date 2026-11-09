# Isolated conversation acceptance environment

Status: prepared for plan review, not deployed. The existing production Render
service and database are not adopted, copied, resumed, or modified.

## Stack
Use infra/render.chat-review.yaml from copilot/flow-conversation-reliability,
with create_new and automatic Blueprint synchronization disabled. It defines
one Free web service and one separate Free Postgres database, a new generated
session secret, external database access blocked, and manual app deploys.
It keeps normal authentication and permission checks active (ENVIRONMENT=staging).
No production secrets, external platform credentials, mail credentials or AI keys
are copied. Do not upgrade plans automatically if Free resources are unavailable.
Free resources have limits; review current Render quotas/expiry before approval:
https://render.com/docs/free .

## Plan and activation
Native Blueprint creation/planning validates remote config and does not provision
the stack until the reviewed plan is approved. Inspect the exact workspace,
create-only actions and Free plans. The new app may initialize/migrate only the
new empty database. Never point DATABASE_URL at the existing production database.

After authorized activation, record the service ID, URL, live deploy and exact SHA.
The API and frontend must use the same source revision. Keep auto-deploy off.
The service is publicly reachable and still requires real login; the database
uses separate credentials. Do not seed a shared password or introduce auth bypasses.

## Frontend preview routing
Do not change vercel.json or the production project's API destination. Generate
a separate config with the actual API URL returned by Render:

    python scripts/prepare_chat_preview.py --backend-url ACTUAL_APPROVED_HTTPS_ORIGIN --output /tmp/flow-chat-preview.json

The generator only accepts a flow-chat-review-api onrender.com hostname,
updates API rewriting and CSP connections together, rejects production and
credential-bearing URLs, and refuses to overwrite its source configuration.
Deploy it only as a Vercel preview using the separate local config, preserving the
existing project's identity. Never use a production deployment flag.
No Vercel environment or production routing was changed by this preparation.

## Browser acceptance
Create a disposable test account through normal registration on the isolated API.
Existing production accounts are not copied. Use secure browser sign-in.
Without an AI provider key, test persistence/rejection and recovery only; a
successful generated reply is NOT verified. Enable an approved provider through
secret settings with an agreed test budget before testing completion.

Check: exact multiline input, new conversation, saved-history reload, switch
between two conversations, interrupted response status, retained rejected draft,
and isolation from a second test account. Test the 32,000-character default chat
contract separately from custom-agent and app-builder limits. Record observed
results; never turn an absent provider or failed login into a PASS.

## Stop / cleanup
No payment, email, social publication, original enterprise SQL, or production data
is used. Do not delete resources or data automatically after testing; identify the
test resources and obtain the normal deletion confirmation when cleanup is due.
