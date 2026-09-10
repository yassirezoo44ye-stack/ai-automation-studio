import { useCallback, useEffect, useState } from "react";
import { sessionsService } from "../services/devicesService";
import type { DeviceSession, CreateSessionPayload, LayoutEntry } from "../types/devices.types";

interface UseDeviceSessionResult {
  sessions: DeviceSession[];
  activeSession: DeviceSession | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
  createSession: (payload: CreateSessionPayload) => Promise<DeviceSession>;
  startSession: (sessionId: string) => Promise<void>;
  stopSession: (sessionId: string) => Promise<void>;
  updateLayout: (sessionId: string, layout: LayoutEntry[]) => Promise<void>;
}

export function useDeviceSession(): UseDeviceSessionResult {
  const [sessions, setSessions] = useState<DeviceSession[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await sessionsService.list();
      setSessions(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load sessions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetch(); }, [fetch]);

  const activeSession = sessions.find(s => s.status === "active") ?? null;

  const createSession = useCallback(async (payload: CreateSessionPayload): Promise<DeviceSession> => {
    const session = await sessionsService.create(payload);
    await fetch();
    return session;
  }, [fetch]);

  const startSession = useCallback(async (sessionId: string) => {
    await sessionsService.start(sessionId);
    await fetch();
  }, [fetch]);

  const stopSession = useCallback(async (sessionId: string) => {
    await sessionsService.stop(sessionId);
    await fetch();
  }, [fetch]);

  const updateLayout = useCallback(async (sessionId: string, layout: LayoutEntry[]) => {
    await sessionsService.updateLayout(sessionId, layout);
    await fetch();
  }, [fetch]);

  return {
    sessions,
    activeSession,
    loading,
    error,
    refetch: fetch,
    createSession,
    startSession,
    stopSession,
    updateLayout,
  };
}
