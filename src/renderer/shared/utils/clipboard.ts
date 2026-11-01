/** Resolve only after a browser copy method confirms success. */
export async function copyText(text: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
  } catch { /* Try the browser's legacy copy method below. */ }
  const previous = document.activeElement;
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.cssText = "position:fixed;inset:0;opacity:0;pointer-events:none";
  document.body.appendChild(field);
  try {
    field.focus(); field.select();
    if (typeof document.execCommand !== "function" || !document.execCommand("copy")) throw new Error("Copy failed");
  } finally {
    field.remove();
    if (previous instanceof HTMLElement) previous.focus({ preventScroll: true });
  }
}
