/**
 * Utility helpers for the AI Tools section catalogue.
 * Kept separate from the component file so react-refresh can do its job.
 */
import type { AppSection } from "../components/Panels/AppTreePanel";

/** Returns true for every AppSection that belongs to the AI-tools catalogue */
export function isAiToolsSection(section: AppSection | null): section is AppSection {
  if (!section) return false;
  const ids: AppSection[] = [
    "ai-assistants",
    "no-code-dev",
    "content-production",
    "productivity",
    "creativity-design",
    "automation-int",
  ];
  return (ids as string[]).includes(section);
}
