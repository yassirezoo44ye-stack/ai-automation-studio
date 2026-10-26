# Flow Career Assistant

Implemented on `feature/career-assistant`, based on `ba1131195e933534f50c2e95ba3b39d2a6037cf6`.
Route: `/careers`, available under Operate in the sidebar.

## Delivered flow

1. User records their own professional summary, target roles, industries, skills, languages,
   locations, experience, minimum monthly AED pay and optional UAE driving licence status.
2. Paste a full LinkedIn/Indeed email (plain text or HTML), or grant separate Gmail read-only consent.
3. Extract supported direct job IDs, remove personalised tracking parameters, deduplicate by canonical
   job URL per user and organisation, preserving application status on repeat import.
4. List supporting keyword evidence, known gaps, unresolved checks, salary source/period and closing date.
   A score is an evidence match out of 100, **never an acceptance probability**. Full descriptions are
   not claimed when only an email excerpt is available. Unknown abilities remain questions, not facts.
5. Explicitly check the public listing where accessible. Closed pages are excluded from recommendation;
   redirects, sign-in walls, HTTP failures and oversized responses remain unverified. Browser automation
   and scraping behind authentication are not included.
6. Save application status or generate an editable, unsent English application draft using only the
   user's supplied summary. The user must review, add their name, attach a CV, and submit themselves.
7. Optional daily Gmail polling, at the user's opt-in, imports new alerts and creates a private in-app
   notification. No paid model calls, no email sending and no automatic applications.

## Gmail setup (required before real sync)

Configure these backend variables from your Google Cloud OAuth web client:

- `CAREER_GOOGLE_CLIENT_ID`
- `CAREER_GOOGLE_CLIENT_SECRET`
- `CAREER_GOOGLE_REDIRECT_URI`: exact frontend URL, for example
  `https://ai-automation-studio-kohl.vercel.app/careers`.

Enable Gmail API and register that exact redirect URI in Google Cloud. Google **login** does not grant
mailbox access. This feature requests only `https://www.googleapis.com/auth/gmail.readonly`, using
server-side code exchange, PKCE S256, ten-minute one-use state and offline consent. Read-only Gmail
is a restricted Google scope; testing/verification and permitted users must be configured in the
Google project as applicable. This implementation does not assert that Google has approved it.

Authorisation callback returns to the frontend. It exchanges code/state through the authenticated
backend with the same verified user and workspace. Neither access nor refresh tokens are returned to
the frontend. Refresh tokens and temporary PKCE verifiers are encrypted with a namespaced Fernet key
from `SESSION_SECRET`. Keep this secret stable; rotation requires Gmail reconnection. The UI stores
only the pending workspace ID in sessionStorage, not credentials. Disconnect deletes the local
credentials and waits for an in-flight import to complete; saved jobs/profile remain available.

Official protocol references:
- https://developers.google.com/workspace/gmail/api/auth/web-server
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/workspace/gmail/api/auth/scopes

## Storage and execution

Five idempotent PostgreSQL tables are created by the existing startup schema mechanism:
`career_profiles`, `career_jobs`, `career_gmail`, `career_oauth_states`, `career_gmail_messages`.
Every private CRUD query includes both verified `organization_id` and authenticated `user_id`.
Organisation membership is required. Being a colleague in the same organisation does not grant
access to another user's profile, drafts, jobs or mailbox credentials.

Polling is a managed asyncio task following the web server lifecycle. It checks due connections every
minute, only for active memberships and organisations; per-owner PostgreSQL advisory locks prevent
overlapping imports across workers. Due time is rechecked after acquiring the lock. Schedules are
disabled by default and support intervals from 6 to 168 hours (UI default: 24). Provider failures are
shown safely and deferred for an hour. Shutdown cancels and awaits the task before closing the pool.
Polling requires an awake server; the next due run happens when a sleeping service resumes.

Gmail query is fixed to recognised LinkedIn/Indeed job-alert senders within the last 14 days,
excluding Spam and Trash. At most 100 matching messages are listed per run, newest-first; already
processed IDs skip body retrieval. Backlogs beyond that window/bound need a future paginated cursor.
Provider retrieval has a 90-second total timeout. Message arrival time is stored separately from the advertised application deadline. Attachments
are not downloaded. No mailbox data is sent to any model.

## Boundaries and known limits

- Exact term matching, not semantic or recruiter-calibrated prediction; include English/Arabic
  keywords in the editable profile. Language gate parsing currently recognises English language names.
- Supported direct URLs: LinkedIn numeric job IDs and Indeed `jk` IDs. Ad redirects without a public
  job ID are not reverse-engineered. Unsupported messages are counted rather than populated with guesses.
- The parser handles common email layouts, not arbitrary web pages or every newsletter layout.
- Public-page verification is best-effort; 3xx responses are not followed. The full requirements still
  need user review, especially specialised experience and complex language requirements.
- Salaries retain source uncertainty, period and OTE/commission/estimate classification. Only listed
  monthly lower bounds participate in salary points/sort. No annual-to-monthly conversion is implied.
- Latest 500 jobs are returned; server-side pagination, CV upload/parsing, semantic AI ranking,
  WhatsApp delivery and application submission are outside this implementation.
- Live Google consent, production deployment and persistence must be verified after release; connecting a mailbox requires user consent in Flow.

## Verification

Verified: 70 backend tests (career assistant + notifications), all 384 frontend tests (including 16 career/navigation tests), typecheck, scoped ESLint, scoped Ruff and production build.

Run focused checks:

```sh
python -m pytest tests/test_careers.py tests/test_notifications.py -q
npx vitest run src/renderer/features/careers/CareersPage.test.tsx src/renderer/features/settings/__tests__/SidebarNav.test.tsx
npm run typecheck
npm run build
```

Additional schema validation was executed against isolated PostgreSQL WASM (PGlite), covering
idempotent DDL, per-owner duplicate keys, isolation predicates, status preservation, schedule defaults
and interval constraints. This validates SQL, not a production asyncpg connection. A native temporary
PostgreSQL server could not start because this execution environment does not allow switching users.
Browser visual testing was unavailable because the Chromium download failed; component interactions
were checked with Testing Library/jsdom. Live Google consent, production persistence, daily runtime
and deployment remain unverified.
