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
  const mountedRef = useRef(false);
  const latestRef = useRef({ project, unsaved, onSave, onSaved, onError, enabled });
  useEffect(() => { latestRef.current = { project, unsaved, onSave, onSaved, onError, enabled }; });
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const save = useCallback(async function saveLatest() {
    const snapshot = latestRef.current;
    if (savingRef.current || !mountedRef.current || !snapshot.enabled || !snapshot.unsaved) return;
    savingRef.current = true;
    try {
      await snapshot.onSave(snapshot.project);
      const current = latestRef.current;
      // A response for revision A cannot mark newer revision B as saved.
      if (mountedRef.current && current.enabled && current.project === snapshot.project) current.onSaved();
    } catch (err) {
      if (mountedRef.current) latestRef.current.onError?.(err instanceof Error ? err : new Error(String(err)));
    } finally {
      savingRef.current = false;
      const current = latestRef.current;
      // An edit can arrive while the request is in flight and its debounce can
      // fire before that request finishes. Queue the latest revision explicitly.
      if (mountedRef.current && current.enabled && current.unsaved && current.project !== snapshot.project) {
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => { void saveLatest(); }, DEBOUNCE_MS);
      }
    }
  }, []);

  useEffect(() => {
    if (!enabled || !unsaved) return;

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      void save();
    }, DEBOUNCE_MS);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [enabled, unsaved, project, save]);
}
