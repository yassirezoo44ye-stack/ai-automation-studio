# Flow Business — evidence-based Leads security review (2026-11-15)

Scope: static source inspection only; no runtime or integration tests have been executed. Do not merge or deploy without owner approval.

## Inspected
- `app/routers/leads.py` on main: capture, lead creation, authorization and automation enqueue.
- `app/core/careers/service.py` on main: separate Career Assistant user/org isolation; not a Flow Business dependency.

## Verified in source (not yet proven in production)
- Authenticated leads list/create use `require_permission('leads','read'/'write')` and pass `ctx.org_id` into service calls.
- External `POST /api/leads/capture` requires `X-API-Key` with write permission and a nonempty organisation id; organisation comes from the credential, not user-supplied request body.
- Capture is rate-limited to 30 calls per 60-second window per dependency configuration; verify the actual limiter's keying and distributed behavior separately.
- Automation enqueue uses `lead-followup:{org_id}:{lead_id}` idempotency key and returns `no_definition`, `enqueued`, or `failed`.
- `/api/leads/{id}/ai-followup` is documented as a draft, not a send operation; inspect implementation and integration before making promises.

## Potential issues requiring tests/review
1. **PII in source:** capture concatenates `message[:200]` into `source`. This mixes free-text lead content with a metadata field that may be logged, displayed or exported. Determine all downstream sinks; prefer separately stored, access-controlled message data with retention policy or omit message until a lawful storage path exists.
2. **Partial failure:** capture creates a lead, qualifies via AI, enqueues automation, and optionally sends notifications in a single request. Verify AI outage behavior and retry semantics; avoid duplicate lead creation on client retries.
3. **Idempotency semantics:** key is per lead, not per external submission. Verify duplicate HTTP POSTs don't create duplicate leads and that retries of failed enqueue can recover safely.
4. **Automation approval:** enqueue may start a workflow when a definition is enabled. Verify external messages cannot be sent without human approval, regardless of workflow configuration.
5. **Data isolation:** inspect lead service SQL and test read/write/notification/export paths across two orgs, not just router dependency signatures.
6. **API keys:** verify scopes, rotation, revocation, expiry, storage and rate limiting. Do not embed an organisation's secret API key in browser-delivered JavaScript.
7. **Privacy:** confirm retention, deletion, lawful collection, breach response and cross-border AI-provider disclosures before accepting real leads.

## Test acceptance criteria
- Org A cannot list, fetch, update, qualify, draft or export Org B leads; response must not leak existence.
- Invalid/revoked/wrong-scope keys cannot capture leads. Org identity cannot be forged in JSON.
- Replayed capture request with a stable client submission id does not duplicate a lead; verify actual implementation before claiming this.
- Missing AI provider produces a defined recoverable outcome without lost/duplicate leads.
- No outbound message occurs before explicit user approval.
- No raw lead message is exposed through generic source/telemetry or unrelated notifications.
- Delete/export/retention flows meet documented policy and customer contract.

## Jurisdiction checkpoint
UAE official guidance says free-zone entities need appropriate mainland approvals/licensing for direct mainland sales. Do not equate cheap Fujairah package with lawful Dubai/Sharjah customer delivery. Confirm SaaS-specific activity codes and written authority guidance. Source: https://u.ae/en/information-and-services/business/doing-business-in-free-zones/running-a-business-in-a-free-zone-

## Next engineering change
Investigate `app/core/leads/service.py`, `app/core/api_keys.py` and lead automation execution path, then add tests and minimal fixes on a dedicated branch. No live customer data, payment enablement, deployment or main merge.
