import { useState, useCallback, useRef } from "react";
import type { FactoryProject, FactoryPhase } from "../types/saasFactory.types";
import {
  submitIdea,
  getProject,
  resumeProject,
  listProjects,
  deleteProject,
} from "../services/saasFactoryService";

const TERMINAL_PHASES: FactoryPhase[] = ["LIVE", "FAILED", "CANCELLED"];
const POLL_MS = 4000;

export function useSaasFactory() {
  const [project, setProject] = useState<FactoryProject | null>(null);
  const [projects, setProjects] = useState<FactoryProject[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback((id: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const p = await getProject(id);
        setProject(p);
        if (TERMINAL_PHASES.includes(p.phase)) stopPolling();
      } catch {
        stopPolling();
      }
    }, POLL_MS);
  }, [stopPolling]);

  const submit = useCallback(async (idea: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await submitIdea(idea);
      const initial = await getProject(res.project_id);
      setProject(initial);
      startPolling(res.project_id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start pipeline");
    } finally {
      setLoading(false);
    }
  }, [startPolling]);

  const resume = useCallback(async (id: string) => {
    setError(null);
    try {
      await resumeProject(id);
      startPolling(id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to resume");
    }
  }, [startPolling]);

  const loadProjects = useCallback(async () => {
    try {
      const res = await listProjects();
      setProjects(res.projects);
    } catch {
      /* ignore */
    }
  }, []);

  const remove = useCallback(async (id: string) => {
    await deleteProject(id);
    setProjects(prev => prev.filter(p => p.id !== id));
    if (project?.id === id) setProject(null);
  }, [project]);

  const openProject = useCallback((p: FactoryProject) => {
    setProject(p);
    if (!TERMINAL_PHASES.includes(p.phase)) startPolling(p.id);
  }, [startPolling]);

  return {
    project, projects, loading, error,
    submit, resume, remove, loadProjects, openProject,
    stopPolling,
  };
}
