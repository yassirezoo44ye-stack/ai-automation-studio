import { useCallback, useEffect, useState } from "react";
import { devicesService } from "../services/devicesService";
import type { Device } from "../types/devices.types";

interface UseDevicesResult {
  devices: Device[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
  revokeDevice: (deviceId: string) => Promise<void>;
  deleteDevice: (deviceId: string) => Promise<void>;
}

export function useDevices(): UseDevicesResult {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await devicesService.list();
      setDevices(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load devices");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetch(); }, [fetch]);

  const revokeDevice = useCallback(async (deviceId: string) => {
    await devicesService.revokeDevice(deviceId);
    await fetch();
  }, [fetch]);

  const deleteDevice = useCallback(async (deviceId: string) => {
    await devicesService.deleteDevice(deviceId);
    setDevices(prev => prev.filter(d => d.id !== deviceId));
  }, []);

  return { devices, loading, error, refetch: fetch, revokeDevice, deleteDevice };
}
