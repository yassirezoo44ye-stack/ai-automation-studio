# Flow Business — UAE launch readiness (draft; not legal advice)

Status: **BLOCKED FOR PAID LAUNCH** until licensing, payment-provider verification and privacy controls are evidenced. This document is a planning checklist, not evidence of compliance or production readiness.

## Proposed pilot
Offer: AI lead capture, qualification, human-approved follow-up drafts, and team notifications for UAE SMEs. Target pilot: 6 customers × AED 1,500/month = AED 9,000 gross monthly recurring revenue (scenario, not forecast or profit). Use synthetic demo data only until controls pass.

## Hard launch gates
- [ ] **Licensing:** Confirm jurisdiction (Dubai mainland or selected free zone), precise activity covering SaaS/software and business automation, ownership eligibility, approvals, registered business name, licence issuance, and lawful invoicing. Initial approval alone is not authorisation to trade. Record licence number, activity, expiry and official evidence in private records, never this repo.
- [ ] **Payment:** Keep live checkout disabled until legal entity/permit and business verification are accepted by the chosen provider. Stripe UAE requires UAE trade licence or freelancer permit and business verification. Never use another person's account or misrepresent the entity.
- [ ] **Tax:** Review VAT registration threshold (AED 375,000 mandatory taxable supplies/imports, AED 187,500 voluntary subject to conditions); review corporate-tax registration and obligations separately with qualified UAE adviser. Do not confuse VAT threshold with corporate tax.
- [ ] **Data inventory:** List lead name, phone, email, message, source, consent/legal basis, processing purpose, retention, vendors, storage regions, and any cross-border transfer. Confirm controller/processor roles and customer agreements.
- [ ] **Privacy:** Publish a verified privacy notice, implement rights handling (access/correction/deletion where applicable), retention/deletion, security safeguards, vendor agreements and transfer assessments. Obtain appropriate lawful basis for each use; do not assume consent covers unsolicited marketing.
- [ ] **Tenant isolation:** Test every leads, workflow, notification, export and billing endpoint for cross-organisation access (including IDOR); no production lead data in AI logs, analytics, or test fixtures.
- [ ] **AI safety:** Label AI qualification as a suggestion; allow human override; require explicit human approval before external follow-up; do not fabricate salary, conversion metrics, or promises.
- [ ] **Security:** Verify RBAC, encryption in transit, secrets storage, audit logs, backup/restore, rate limits, incident response, and deletion on cancellation.
- [ ] **Billing:** Verify prices, tax treatment, subscription consent, invoices, cancellation/refunds, payment webhook signature, idempotency, and failed-payment behavior in test mode.
- [ ] **End-to-end:** With synthetic records, demonstrate capture → qualify → approve → notify → follow-up status → export/delete, with tests and screenshots/logs.
- [ ] **Go/no-go:** Record evidence, remaining risks and explicit owner approval before merging or production deployment.

## Initial execution backlog (separate PRs)
1. Audit existing Leads/Automate/Billing endpoints and permissions; produce evidence-based gap list.
2. Add automated tenant-isolation and workflow-idempotency regression tests.
3. Implement a **demo-only** Business dashboard reusing existing components; no live payment activation.
4. Draft privacy notice and B2B service terms for local legal review.
5. Validate payment test mode and webhook behavior, only after verifying provider setup.
6. Pilot with synthetic data; seek explicit approval for any real-user processing or production launch.

## Official reference links (verify current rules before acting)
- Dubai DET business licensing: https://www.dubaidet.gov.ae/en/licences-and-permits/business-licensing
- UAE Ministry of Economy business establishment: https://www.moet.gov.ae/en/establishing-companies
- UAE government personal data protection overview: https://u.ae/en/about-the-uae/digital-uae/data/data-protection-laws
- Federal Tax Authority VAT registration: https://www.tax.gov.ae/en/taxes/Vat/vat.topics/registration.for.vat.aspx
- Stripe UAE business types: https://support.stripe.com/questions/selecting-a-business-type-for-a-uae-account?locale=en-GB
- Stripe UAE verification: https://support.stripe.com/questions/verification-of-businesses-in-the-uae

## Change control
Flow only; do not mix with Axon. Do not merge to main, deploy, enable live payments, or contact customers without explicit owner approval.
