# Flow Food Sales — customer discovery and pilot gate

Status: hypothesis, **not validated**. No signed pilots, confirmed interviews or paying customers as of 2026-11-15. This document is a research protocol, not a product requirement or authorization to contact customers.

## Target and core hypothesis

Small UAE food distributors receive orders via representatives, phone, messaging and internal systems. A lightweight shared order-status and exception-follow-up view may reduce the time to identify and resolve stalled orders. **Do not assume that this is painful or that firms will pay.**

## Contacted organizations

| Company | Address used | Initial contact | Reply / interview |
| --- | --- | --- | --- |
| Al Deek Foodstuff | sales@aldeekuae.com | Email sent | None observed |
| Mermaid Foodstuff | info@mermaidfoodstuff.com | Email sent | None observed |
| Al Turab Foodstuff | info@alturabfood.com | Email sent | None observed |
| Tulsidas | trade@tulsidas.com | Email sent | None observed |
| Comfi Foodstuff | info@comfifoodstuff.com | Email sent | None observed |

Source of truth for delivery and replies is Gmail, not this static document. Do not resend automatically or infer consent from silence.

## Interview script (10–15 minutes)

1. Walk me through the most recent order that was delayed. What happened, and who discovered it?
2. Which channels create orders? Who enters them into the system of record?
3. How does a supervisor identify an order blocked by stock, credit, preparation or delivery?
4. What was the measurable cost of the most recent delay, if known?
5. Which tools already solve parts of this process? What remains manual?
6. If this problem disappeared, what would change? Who approves software purchases?
7. Would you trial a narrow workflow with synthetic data? Under what conditions?
8. Only after demonstrating value: would a paid pilot be considered? At what budget and approval process?

Record direct observations separately from guesses. Do not request real customer records, payment details or confidential commercial information.

## Minimal demo: synthetic data only

Show three orders: new, blocked (stock unavailable), and completed. Each order has an owner, created time, next action, due time, and event history. The blocked order must visibly show reason, assignee and overdue notification. Use existing Flow Teams, Leads, Notifications and Automation only where appropriate; **an order is not a lead**. No ERP, inventory, accounting, WhatsApp messaging or payments integration in this pilot.

## Acceptance gate before engineering expansion

- At least five real conversations with relevant sales/operations staff, ideally ten.
- At least three independent companies describe a recurring, recent and costly order-status/follow-up problem.
- At least one company explicitly agrees to evaluate a demo.
- Test willingness to pay with a concrete offer, not hypothetical enthusiasm.
- Record reasons for refusal and competing tools.

These are decision thresholds, not achieved results. If unmet, refine the problem or segment; do not expand product scope.

## Discovery record template

Date | Company | Interviewee role | Evidence of recent incident | Existing process | Frequency | Cost evidence | Decision maker | Demo interest | Payment signal | Next step | Consent/notes.

## Safety and release controls

- No customer contact or follow-up without user authorization; monitoring replies is allowed.
- No automatic messages, no customer-data imports, no real payment flows.
- No main merge or production deployment without explicit user approval.
- Keep Axon separate from Flow.
