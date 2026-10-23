---
name: ui-ux-pro-max
description: >
  Apply systematic UI/UX design principles to Flow. Use when asked to:
  audit a screen for UX issues, establish design consistency, improve
  navigation or user flows, review accessibility, optimize for mobile,
  or define design tokens and spacing systems. Trigger phrases: "UX",
  "user experience", "design system", "tokens", "consistency",
  "navigation flow", "usability", "accessibility audit", "mobile UX",
  "onboarding", "empty state", "error state", "design review".
  Do NOT trigger for pure code refactoring with no visual/UX impact.
---

# UI/UX Pro Max Skill — Flow Project

## Guiding Principles

1. **Clarity over cleverness** — every action should be obvious without a tooltip.
2. **Progressive disclosure** — show what the user needs now; reveal complexity on demand.
3. **Consistent affordances** — if something looks clickable, it is clickable everywhere.
4. **Forgiving design** — make destructive actions reversible; confirm before permanent changes.
5. **Speed perception** — optimistic updates, skeleton screens, and progress indicators over spinners.

## Design Token Audit (do this first on any UX task)

Before proposing design changes, read:
- `tailwind.config.js` / `tailwind.config.ts` for color, spacing, and typography scales.
- Any `tokens.css`, `variables.css`, or theme file in `src/`.
- Existing component styles to identify what tokens are actually used vs. defined.

If inconsistencies exist (components using ad-hoc values instead of tokens), document them.
Only propose token standardisation as a separate, scoped task — not as a side effect of a feature.

## UX Heuristics Checklist (Nielsen's 10, adapted for Flow)

Run this on any screen under review:

| # | Heuristic | Check |
|---|-----------|-------|
| 1 | **Visibility of system status** | Does the UI show loading, success, and error states? |
| 2 | **Match with real world** | Do labels use the user's vocabulary, not internal code names? |
| 3 | **User control and freedom** | Can the user undo/cancel any action? |
| 4 | **Consistency and standards** | Do similar actions look and behave identically across screens? |
| 5 | **Error prevention** | Are destructive actions gated behind confirmation? |
| 6 | **Recognition over recall** | Are options visible; does the user have to remember anything? |
| 7 | **Flexibility and efficiency** | Do power users have shortcuts? |
| 8 | **Aesthetic and minimalist design** | Is every element on the screen earning its place? |
| 9 | **Help users recognise and recover from errors** | Are error messages specific and actionable? |
| 10 | **Help and documentation** | Are empty states and first-run experiences guided? |

## Navigation Principles for Flow

- Max **2 clicks** to any primary action from the dashboard.
- Active state is always visible in the sidebar/nav.
- Breadcrumbs on detail pages so the user knows where they are.
- Back navigation never loses unsaved form state without warning.
- Mobile: bottom navigation or hamburger for items > 5; never a horizontal nav bar that requires scrolling.

## State Coverage Requirements

Every screen and component must handle all six states:

1. **Loading** — skeleton or spinner (use skeleton for content-heavy areas).
2. **Empty** — friendly message + primary CTA, not a blank page.
3. **Partial data** — e.g., list with 1 item; layout must not break.
4. **Full / nominal** — the happy path.
5. **Error** — specific message (not "Something went wrong"), retry action.
6. **Disabled / read-only** — visually distinct; reason given if non-obvious.

## RTL/LTR UX Rules

- Icons with directionality (arrows, chevrons, play buttons) must flip in RTL.
- Text alignment follows reading direction automatically via `text-align: start`.
- Form field labels are always on the correct side for the language direction.
- Toast/notification positioning adapts to direction (top-right in LTR → top-left in RTL).
- Progress indicators run in the correct direction.

## Mobile UX Standards

- Touch target minimum: **44 × 44 px**.
- Primary action always reachable with one thumb (bottom 2/3 of screen).
- No hover-only affordances — every hover state must have a tap equivalent.
- Modals on mobile: full-screen or bottom sheet, not small centered dialogs.
- Font minimum: 16px for body text (prevents iOS auto-zoom on inputs).
- Input fields: correct `inputmode` attribute (`numeric`, `email`, `tel`) for appropriate keyboards.

## Delivering a UX Review

Structure findings as:
1. **Critical** — blocks task completion or causes data loss.
2. **Major** — significantly hurts usability but has a workaround.
3. **Minor** — polish and consistency issues.
4. **Suggestions** — optional improvements.

For each finding: current behaviour → problem → proposed fix → effort estimate (S/M/L).
Never implement fixes from a UX review without separate approval.
