# Legal pages (draft)

`/privacy`, `/terms` and `/refunds` are public pages rendered from
`src/renderer/features/legal/content.ts` (English and Arabic).

They are **drafts written from what the code does, not legal advice**.
Before launch:

1. Fill in `LEGAL_ENTITY` (legal name, registered address, contact e-mail).
2. Confirm the business choices: minimum age 16, 7-day refund on a first
   subscription payment, 14 days for faulty digital products, Dubai courts.
3. Have a UAE-licensed lawyer review both languages.
4. When either text changes, bump `LEGAL_VERSION` (content.ts) and
   `TERMS_VERSION` (app/core/legal.py). New accounts store the version they
   accepted in `users.terms_version` / `users.terms_accepted_at`.

Privacy rights in the product: Settings → Account offers "Download my data"
(`GET /api/auth/me/export`) and "Delete account" (`DELETE /api/auth/me`), which
also cancels Stripe subscriptions of organizations only that user belongs to
and refuses (409) while the user is the sole owner of a shared organization.
