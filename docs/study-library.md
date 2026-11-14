# Visual Study Library — افهمها بصريًا

The library at `/study-library` sells access to a collection of original Arabic
summaries. Payhip handles a single, one-time purchase. Flow receives purchase
and full-refund notifications and serves PDFs only to matching, verified users.
The existing general-purpose book library is unchanged.

## Required configuration

Set these only in the backend's secret/environment settings; never put real
values in Git, frontend `VITE_*` variables, a product description or task prompt:

| Variable | Meaning |
| --- | --- |
| `STUDY_LIBRARY_ADMIN_EMAIL` | Verified Flow account allowed to upload summaries |
| `STUDY_PAYHIP_API_KEY` | Payhip Settings → Developer API key |
| `STUDY_PAYHIP_PRODUCT_KEY` | Exact key of the new library-access product |
| `STUDY_PAYHIP_CHECKOUT_URL` | `https://payhip.com/b/` followed by that same key |
| `STUDY_LIBRARY_PUBLISH_KEY` | Optional automation secret, minimum 32 random characters |

No default admin, checkout link, purchase or sample buyer is created. Missing
payment configuration denies access and suppresses the checkout button. Platform
admin and publishing credentials can upload content; they cannot create a buyer
purchase or bypass email verification for a buyer.

## Payhip setup (once)

1. Create a new digital product for **library access**, distinct from the
   earlier job-search product and the standalone summary files.
2. Clearly describe the available summaries, personal-use licence and whether
   access includes future releases. Set your reviewed price. This integration
   supports one-time paid access, not recurring subscriptions or gift purchases.
3. In the buyer download/content area, include your actual frontend origin
   followed by `/study-library`. Instruct buyers to register/sign in with the
   purchase email and verify that email. A link alone grants no access.
4. Set the five backend variables above as appropriate. Register the actual
   backend origin followed by `/api/study-library/payhip` in Payhip Developer
   webhooks, selecting `paid` and `refunded`. Never include secrets in the URL.
5. Complete a controlled paid test and full refund, verifying access and denial
   before announcing the product. A free order is intentionally not a paid grant.
   Existing orders are not automatically imported. Refunds received for unknown
   purchases create a tombstone; later/replayed paid events cannot restore access.

Official source: https://help.payhip.com/article/115-webhooks.
Payhip's signature is **SHA-256 of the API key**, a static bearer credential,
not an HMAC over the payload. Compare it in constant time, protect the endpoint
with HTTPS, and never log payloads/signatures. The integration checks product,
transaction shape, buyer email and positive paid price before storing a grant.
Only full refunds revoke access; a different active purchase remains valid.

## Publish reviewed content

The verified administrator can use the upload form at the bottom of the library.
Automation can use `scripts/publish_study_batch.py batch.json`. Configure the
Flow HTTPS origin in `STUDY_LIBRARY_BASE_URL` and the same publish secret on
the runner. No browser session or Payhip CAPTCHA is needed to add Flow content.

Manifest example (repeat for three **distinct** reviewed lessons):

```json
[
  {
    "slug": "fractions-basics",
    "title": "الكسور ببساطة",
    "subject": "math",
    "description": "ملخص تأسيسي للكسور مع أمثلة وثلاثة أسئلة بإجاباتها.",
    "pdf": "01-Fractions/Buyer-File.pdf",
    "cover": "01-Fractions/Product-Cover.png"
  }
]
```

The actual batch must have three entries. Subject keys: `math`, `physics`,
`chemistry`, `biology`, `english`, `computing`. Files must be under the manifest
directory. PDF limit: 8 MiB, 1–40 pages, readable and unencrypted. Cover: PNG,
up to 2 MiB, 200–3000 pixels in each dimension. Request body cap: 11 MiB.

Files are stored in PostgreSQL, outside public static routes and outside Git.
Public catalog/cover responses contain no PDF bytes, download token or buyer
data. File downloads require fresh authorization and use private/no-store caching.
Concurrent publishers share a PostgreSQL transaction advisory lock. At most
three new lessons are accepted for each Asia/Dubai date. Retrying the same
slug/PDF is idempotent; changed files require a new slug. Reused PDF hashes fail.

## Daily production is a separate integration

The existing ChatGPT task prepares three reviewed lesson files. That task does
not yet call this API. To close the loop, provision an authenticated runner,
give it the reviewed batch and server-side publishing secret, and run a real
three-item import. Do not claim automatic delivery into Flow before that test.
No paid AI provider, external message or real purchase is invoked by this code.

## Verification

Run the focused backend and frontend tests and the normal production build.
`tests/test_study_library_postgres.py` additionally exercises real PostgreSQL
transaction/refund/concurrency behavior when `STUDY_TEST_DATABASE_URL` points
to an isolated test database. It creates and drops its own temporary schema.
Never point it at a production database.

## Linked content workflow inside Flow

The library administrator can open **إدارة المحتوى · ربط المكتبة والمنصات**
inside `/study-library`, after selecting an organization they own or administer.
This is a persisted platform workflow, not the local content-export script.

1. Add a lesson using the existing PDF/cover publisher, then select that lesson.
2. Enter a voiceover script and separate TikTok, Instagram and YouTube captions.
   `lesson-content.json` from a prepared batch can fill the script/caption fields;
   import is local until the user saves. It does not upload a batch or publish.
3. Save a revision. A final public HTTPS video URL is required for approval;
   saving a script alone neither records audio nor renders a video.
4. Review the source PDF, captions, final video and rights, then approve the saved
   revision. Editing content clears the approval. Stale revisions and changed
   source PDF fingerprints cannot be approved or handed off.
5. Create social drafts. One `social_posts` draft per platform is inserted in a
   single transaction and linked back to the workflow. Repeating handoff cannot
   duplicate posts, and no publish jobs or external API calls are triggered.
6. Refresh linked-post statuses to read the actual social publisher state.

Connection cards distinguish an implemented provider, configured service and
saved account. A saved account is not evidence of a valid token or a successful
publish. OAuth uses the existing social account endpoints, after a user clicks
through. YouTube remains unimplemented in the current registry; its draft can be
prepared, but this feature does not claim that YouTube publishing is available.
No tokens, secrets, buyer emails or paid PDF URLs are returned by these endpoints.

The additive schema initializes after the social publisher schema. Every workflow
query is scoped to the authenticated organization and also requires the verified
library administrator plus an organization owner/admin role. A publishing key
cannot authorize these workflow endpoints. PDF access and Payhip verification
are unchanged; a social draft never grants library purchase access. Carousel
rendering and video production remain separate from this first platform handoff.

### Cross-origin social account connection

The authenticated `/api/social/accounts/{platform}/connect` request now returns
an API-origin authorization URL and a one-use ticket (60-second TTL). Flow submits
that ticket as a top-level POST from its configured HTTPS `FRONTEND_URL`. The API
checks the browser Origin before consuming the ticket, sets the HttpOnly/Secure/
SameSite=Lax nonce cookie as a first-party response, and redirects to the provider.
This avoids relying on third-party cookies between Vercel and Render. The form
uses `rel=noopener` (not `noreferrer`, which can suppress the Origin needed here).
Only POST authorize and GET callback paths for the named platforms are exempt
from the session middleware; account listing, connect and publishing remain
session-protected. The existing callback still verifies and consumes state and
matches the browser nonce. Missing/foreign origins, expired tickets, wrong
platforms and replayed requests fail without exchanging credentials.
