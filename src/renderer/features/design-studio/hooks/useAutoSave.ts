import { useEffect, useRef, useCallback } from "react";
import type { DesignProject } from "../types/canvas.types";

const DEBOUNCE_MS = 2000;

interface UseAutoSaveOptions {
  project:    DesignProject;
  unsaved:    boolean;
  onSave:     (project: DesignProject) => Promise<void>;
  onSaved:    () => void;
  onError?:   (err: Error) => void;
  enabled?:   boolean;
}

export function useAutoSave({
  project,
  unsaved,
  onSave,
  onSaved,
  onError,
  enabled = true,
}: UseAutoSaveOptions): void {
  const timerRef   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savingRef  = useRef(false);

  const save = useCallback(async (proj: DesignProject) => {
    if (savingRef.current) return;
    savingRef.current = true;
    try {
      await onSave(proj);
      onSaved();
    } catch (err) {
      onError?.(err instanceof Error ? err : new Error(String(err)));
    } finally {
      savingRef.current = false;
    }
  }, [onSave, onSaved, onError]);

  useEffect(() => {
    if (!enabled || !unsaved) return;

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      void save(project);
    }, DEBOUNCE_MS);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [enabled, unsaved, project, save]);
}
