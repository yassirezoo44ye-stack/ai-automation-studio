---
name: writing-plans
description: >
  Create clear, implementation-ready engineering plans for the Flow project.
  Use when asked to: plan a new feature, break down a task into phases,
  create a technical specification, define acceptance criteria, identify
  risks before implementation, or structure a multi-step engineering effort.
  Trigger phrases: "plan", "create a plan", "break this down", "how should
  we approach", "implementation plan", "phases", "technical spec", "what's
  the approach", "before we start", "map out", "scope this out".
  Do NOT trigger for: simple one-step changes, pure documentation writing,
  or tasks that are already fully specified and ready to implement.
---

# Writing Plans Skill — Flow Project

## Purpose

This skill produces engineering plans — not vague outlines, not marketing docs.
A plan written with this skill must be actionable: a developer should be able to
pick it up and start coding Phase 1 without asking any clarifying questions.

## Plan Structure

Every plan uses this structure. Omit a section only if it genuinely does not apply.

---

### Plan: [Feature/Fix Name]

**Status**: Draft — awaiting approval  
**Created**: [date]  
**Scope**: [one sentence describing what this plan covers and what it explicitly excludes]

---

#### Background

Two to four sentences: why this is needed, what problem it solves, and what the
current state is. Link to any relevant issue, PR, or existing code.

#### Goals

Bullet list. Each goal is a concrete outcome, not a vague aspiration.
- ✓ [Specific measurable outcome]
- ✓ [Specific measurable outcome]

#### Non-Goals (explicitly out of scope)

List what this plan does NOT cover, to prevent scope creep during review.

#### Architecture / Approach

The technical approach in enough detail to evaluate correctness before writing code.
Include:
- Files to be created, modified, or deleted (with paths).
- Data model changes (new tables, columns, or schema changes).
- API changes (new endpoints, changed signatures, removed endpoints).
- State management changes (frontend).
- Any new dependencies and justification for adding them.

#### Phases

Break the work into independently deployable phases. Each phase must:
- Be completable in a single focused session (ideally < 4 hours of work).
- Leave the codebase in a passing-tests state at its end.
- Have a clear done condition.

**Phase 1 — [Name]**
- Tasks: [specific file changes and what each does]
- Done condition: [tests pass + specific behaviour observable]
- Risk: [what could go wrong here]

**Phase 2 — [Name]**
- Depends on: Phase 1
- Tasks: …
- Done condition: …

*(Add phases as needed)*

#### Acceptance Criteria

How we know the whole plan is complete. Written as checkable conditions:
- [ ] [Specific user-facing behaviour works as described]
- [ ] [All new code is covered by tests]
- [ ] [No regression in existing test suite]
- [ ] [Security: no new attack surface introduced]
- [ ] [RTL and LTR both work if UI is involved]

#### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| [Risk description] | Low/Med/High | Low/Med/High | [How we address it] |

#### Open Questions

Questions that must be answered before implementation begins. Each question
must have an owner and a resolution deadline.

- [ ] [Question] — owner: [who decides], needed by: Phase [N]

---

## Rules for This Skill

1. **No implementation without approval.** Plans are proposals. Present the plan and wait for explicit approval before writing any code, running any command, or making any file change.

2. **Identify the highest-risk phase first.** If Phase 2 has a known hard problem, call it out in the plan — do not discover it mid-implementation.

3. **Scope explicitly.** A plan without a Non-Goals section will be interpreted as covering everything adjacent. Always bound the scope.

4. **Flow-specific constraints to reflect in every plan:**
   - Multi-tenant: all new data must be org-scoped with row-level security.
   - Auth: no new unauthenticated endpoints without explicit security justification.
   - RTL: any UI change must work in Arabic RTL.
   - Tests: new backend code needs pytest coverage; new frontend code needs vitest coverage.
   - No new third-party dependencies without listing alternatives considered.

5. **One plan per request.** Do not combine unrelated features into a single plan.
