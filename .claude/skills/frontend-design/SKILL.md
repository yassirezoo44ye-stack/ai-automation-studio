---
name: frontend-design
description: >
  Build polished, production-quality React/Vite UI for the Flow project.
  Use when asked to: improve a screen or component, fix a layout issue, redesign
  a page, add a new UI feature, make a component accessible, or improve
  visual consistency. Trigger phrases: "design", "UI", "interface", "component",
  "layout", "responsive", "looks", "style", "redesign", "improve the screen",
  "make it look", "polish". Do NOT trigger for backend-only changes, test
  writing, or pure data/API work.
---

# Frontend Design Skill — Flow Project

## Context

- **Stack**: React 18 + TypeScript + Vite. CSS Modules and/or Tailwind (check the existing pattern before choosing).
- **RTL/LTR**: Flow supports Arabic (RTL) and English (LTR). Every layout must work in both directions. Use `dir` attribute, logical CSS properties (`margin-inline-start`, `padding-inline-end`, `text-align: start`) instead of `left`/`right` where direction-sensitive. Test visually in both directions.
- **Existing branding**: Preserve the product name "Flow", existing color palette, and logo. Do not introduce a new design system from scratch — build on what exists.
- **Fabric.js Design Studio**: Do not touch or replace it. Canvas-related UI belongs to the existing Design Studio.

## Process

### 1. Read Before Writing

Before writing any new component or modifying a screen:
- Read the existing component file and its CSS/styles.
- Check if a design token file, theme file, or `tailwind.config` exists and use its values.
- Identify the pattern the rest of the codebase uses (CSS Modules vs Tailwind vs inline styles). Match it.
- Check accessibility: does the existing component have ARIA labels, keyboard navigation, focus styles?

### 2. Component Architecture

- Prefer small, single-responsibility components.
- Extract repeated UI patterns into shared components under `src/components/`.
- Use `React.memo` only when profiling shows it is needed — not by default.
- Keep state as local as possible. Lift only when two siblings need the same state.
- Use `forwardRef` when a component needs to expose its DOM node to a parent.

### 3. Visual Quality Standards

Every component delivered must satisfy:
- **Spacing**: consistent with the project's spacing scale (4px base grid or 8px — check existing components).
- **Typography**: uses the project's type scale, not arbitrary `font-size` values.
- **Color**: uses CSS variables / design tokens, never hardcoded hex values for brand colors.
- **States**: hover, focus-visible, active, disabled, loading, empty, and error states are all handled.
- **Borders and radius**: consistent with existing cards/buttons in the project.
- **Shadows**: used sparingly and consistently with existing elevation levels.

### 4. Responsive Layout

- Mobile-first: design from 375px up.
- Use CSS Grid or Flexbox for layout — no absolute positioning for flow layout.
- Test at 375px, 768px, 1024px, 1440px.
- Touch targets minimum 44×44px on mobile.
- Avoid horizontal scroll on any viewport width.

### 5. Accessibility (a11y)

Every interactive element must:
- Be keyboard-reachable (Tab order is logical).
- Have a visible focus indicator (`outline` or `ring`).
- Have an accessible name (`aria-label`, `aria-labelledby`, or visible text).
- Use semantic HTML (`<button>` not `<div onClick>`).
- Not rely solely on color to convey meaning.

### 6. Anti-Patterns to Avoid

- Generic "AI-generated" UI: gradients on every card, rainbow accent colors, excessive animations.
- Replacing working components with a full rewrite when a small targeted fix suffices.
- Hardcoding Arabic strings in JSX — use the i18n system (`t()`).
- Importing a new UI library (shadcn, chakra, MUI) without explicit approval.
- Removing existing `data-testid` attributes (tests depend on them).

### 7. Delivery Checklist

Before marking any UI change done:
- [ ] TypeScript compiles without errors (`tsc --noEmit`).
- [ ] No new ESLint errors.
- [ ] Vitest suite still passes (`npm run test`).
- [ ] Visual check in both LTR (English) and RTL (Arabic) modes.
- [ ] Visual check at mobile width (375px) and desktop (1280px).
- [ ] All interactive states (hover, focus, disabled) are styled.
- [ ] No hardcoded colors or spacing outside the design token system.
