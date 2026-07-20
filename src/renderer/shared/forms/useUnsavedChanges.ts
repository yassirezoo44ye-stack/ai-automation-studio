import { useEffect } from "react";

/**
 * Warns before the user closes the tab/window with unsaved changes.
 * In-app navigation (sidebar clicks) isn't covered — this app has no
 * router to intercept (see AppContext's page state); a future in-app
 * confirmation would need a dedicated dialog wired into AppLayout's
 * page-switch path, not this hook.
 */
export function useUnsavedChanges(dirty: boolean, message = "You have unsaved changes. Leave anyway?") {
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = message;
      return message;
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty, message]);
}
