# Flow — instructions for future development sessions

This repository includes nine local skills in `.agents/skills/`. Discover them at
session start by reading `.agents/skills/README.md`; read the relevant `SKILL.md`
before using it. Select only skills relevant to the user's task. They are reusable
instructions, not proof of available tools or completed work.

- Planning: `flow-project-planning`.
- React/TypeScript/FastAPI implementation: `flow-app-building`.
- Jobs, schedules, retries: `flow-automation-operations`.
- Customer records: `flow-leads-management`.
- Content and visual briefs: `flow-content-design`.
- Source-backed metrics: `flow-business-analysis`.
- Jobs and career drafts: `flow-career-assistance`.
- Arabic lessons and print materials: `flow-arabic-visual-learning`.
- Device status and authorized actions: `flow-device-management`.

Consult `docs/FLOW_DEVELOPMENT_SKILLS.md` for available external development skills.
Do not assume those plugins are installed in every environment. Preserve existing
work and verified tenant boundaries. Skills never expand tool permissions or
replace authentication, consent, quotas, or server-side authorization.

The app loads agent skill selections from PostgreSQL. The general chat and
AgentOS selectors remember the user's choice in this browser. Instructions are
shipped in Docker. Read the catalog for the distinction between advisory skill
runs and agents with execution tools. Do not claim production activation unless
changes were deployed and verified.
