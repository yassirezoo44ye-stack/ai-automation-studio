---
name: canvas-design
description: >
  Create structured visual designs, diagrams, wireframes, and layout assets
  for the Flow project. Use when asked to: draw a system architecture diagram,
  create a wireframe, design a visual layout, produce a flow diagram, sketch
  a data model diagram, or create any visual design asset. Trigger phrases:
  "diagram", "wireframe", "architecture diagram", "flow diagram", "visual layout",
  "sketch", "draw", "design asset", "data model diagram", "sequence diagram",
  "ER diagram". Do NOT replace or modify the Fabric.js Design Studio feature
  in Flow. Do NOT trigger for standard React UI component work — use the
  frontend-design skill instead.
---

# Canvas Design Skill — Flow Project

## Hard Constraint

**Do NOT touch the Fabric.js Design Studio** (`src/pages/DesignStudio*`, `src/components/design-studio/`, or any file importing `fabric`). That is Flow's existing canvas product feature. This skill creates *documentation and planning assets* — diagrams, wireframes, architecture visuals — not changes to the in-product canvas.

## When to Use This Skill

| Request type | Tool to use |
|---|---|
| System architecture diagram | Mermaid (flowchart / C4) |
| Database/ER diagram | Mermaid (erDiagram) |
| User flow / sequence diagram | Mermaid (sequenceDiagram) |
| Wireframe for a new screen | ASCII wireframe or SVG skeleton |
| Component hierarchy | Mermaid (classDiagram or flowchart) |
| Visual design mockup (pixel-level) | HTML/CSS artifact |
| In-product canvas feature | ← Not this skill. Use frontend-design. |

## Diagram Standards

### Mermaid (preferred for architecture and flow diagrams)

Use Mermaid syntax for all text-representable diagrams. Claude Code renders Mermaid natively.

Guidelines:
- Use `flowchart LR` for left-to-right architecture diagrams; `flowchart TD` for top-down hierarchies.
- Use `sequenceDiagram` for API call sequences and user flows.
- Use `erDiagram` for database schemas.
- Keep node labels short (≤ 4 words). Use `:::note` subgraphs to group related nodes.
- Add a brief plain-text summary below every diagram explaining what it shows.

### SVG / HTML Wireframes

For screen wireframes:
- Use simple box layouts — no detailed styling.
- Label every region (nav, sidebar, content, footer).
- Show both LTR and RTL variants if layout differs.
- Mark interactive elements with `[button]`, `[input]`, `[link]`.
- Indicate responsive breakpoints where layout changes significantly.

### Naming and Storage

- Save diagram source files as `docs/diagrams/<name>.md` or inline in the relevant planning document.
- Never commit large binary image files for diagrams that can be expressed as text (Mermaid/SVG).

## Inspection Before Creating

Before creating any diagram:
1. Check `docs/` for existing architecture documentation.
2. Check if a Mermaid diagram already exists for the requested topic.
3. Read the relevant source files to ensure the diagram reflects actual code, not assumptions.

For database diagrams: read `app/*_schema.py` and `migrations/` before drawing.
For API flow diagrams: read the relevant router file before drawing.

## Quality Bar

A good diagram:
- Shows the real system — not a generic "boxes and arrows" placeholder.
- Has a title and a one-sentence caption.
- Uses consistent naming with the codebase (same function/table/component names).
- Is readable without colour (accessible in black-and-white print).
- Has no orphaned nodes (every node is connected to at least one other node).
