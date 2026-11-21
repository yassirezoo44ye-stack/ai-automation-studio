/** Keep this bound aligned with app.routers.build.MAX_BUILD_PROMPT_CHARS. */
export const MAX_BUILD_PROMPT_CHARS = 32_000;

export function promptCharacterCount(prompt: string): number {
  // Python/Pydantic count Unicode code points, not JavaScript UTF-16 units.
  return Array.from(prompt).length;
}

export function buildPromptError(prompt: string): "empty" | "tooLong" | null {
  const count = promptCharacterCount(prompt);
  if (!prompt.trim()) return "empty";
  return count > MAX_BUILD_PROMPT_CHARS ? "tooLong" : null;
}
