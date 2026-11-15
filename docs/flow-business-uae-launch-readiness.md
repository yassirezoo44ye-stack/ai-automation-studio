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


## Jurisdiction decision — 2026-11-15 (research, not approval)
**Provisional candidate:** Creative City Fujairah, advertised Media package AED 3,500 starting price, not a confirmed software/SaaS quote. Confirm software activity codes, package eligibility, total first-year/renewal charges, eligibility of shareholders/managers, visa needs, banking/payment-provider acceptance, and invoicing in writing.

**CRITICAL mainland-sales gate:** Do not assume a Fujairah or UAQ free-zone licence alone authorises selling or providing Flow services directly to Dubai/Sharjah mainland companies. The UAE government says mainland access for free-zone companies is regulated and may require a mainland branch, distributor or relevant permits. Dubai's 2025 Free Zone Mainland Operating Permit is a specific framework with eligibility criteria; do not assume it applies to a Fujairah entity. Obtain written advice from the competent licensing authorities on cross-emirate B2B SaaS and service delivery before charging UAE mainland customers.

**Alternative:** Compare Dubai mainland professional/software activity licence on a full-year cost and lawful domestic-market access basis, even if its headline fee is higher. Do not choose purely on advertised package price.

**Official evidence:**
- https://creativecity.gov.ae/ (Media package starting AED 3,500)
- https://creativecity.gov.ae/faqs/ (activity/operating FAQ; not a mainland permit)
- https://u.ae/en/information-and-services/business/doing-business-in-free-zones/running-a-business-in-a-free-zone- (mainland restrictions)
- https://www.dubaidet.gov.ae/en/newsroom/press-releases/new-growth-for-investors (Dubai-specific permit)
- https://uaqftz.gov.ae/service-license (UAQ service licence limitations)

**Next verification questions to send through official licensing channels:**
1. Which exact activity codes authorise SaaS subscriptions, AI-powered lead management and business-process automation? Are they available in the advertised package?
2. Can the entity invoice and provide remote SaaS to Dubai and Sharjah mainland companies directly? If not, what permit/branch/agent arrangement and costs apply?
3. What are total year-one, year-two renewal, cancellation, visa/no-visa and administrative costs (including VAT)?
4. What shareholder/manager eligibility, age, identity, residency and beneficial-owner documentation is required?
5. Will a locally licensed company of this form qualify for the intended payment provider's onboarding, subject to that provider's own checks?

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
