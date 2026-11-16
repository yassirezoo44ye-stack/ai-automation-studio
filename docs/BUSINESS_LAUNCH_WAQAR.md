# Business Launch — Waqar pilot

Status: isolated domain prototype, **not integrated** into routes, database, UI,
billing, or production. No actual launch has occurred.

## Pilot

Waqar is a hypothetical UAE abaya storefront. Its initial catalog consists of
three illustrative designs, with no inventory, real orders, or payment processing.

## Workflow

IDEA -> FEASIBILITY -> BRAND -> CATALOG -> LAUNCH_PACKAGE ->
PENDING_APPROVAL -> APPROVED.

Approval is a recorded decision only; it does **not** deploy, charge, publish,
or contact customers. All such actions require separately designed permissions
and explicit owner authorization.

## Next implementation gates

1. Design org-scoped persisted project and artifact schemas.
2. Verify RLS and role permissions before adding any endpoints.
3. Connect to the existing AIGateway with org-based metering.
4. Generate labeled hypothetical financial assumptions and original assets.
5. Implement idempotent checkpoints, failure states, and audit evidence.
6. Add UI and integration tests in an isolated test environment.
7. Present diff, CI results, and security review; do not merge or deploy.

Run the domain unit tests with `python -m pytest tests/business_launch/test_workflow.py`.
