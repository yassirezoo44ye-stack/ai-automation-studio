import { apiJSON } from "../../../shared/utils/api";
import type {
  Device,
  DeviceSession,
  EnrollmentToken,
  CreateSessionPayload,
  LayoutEntry,
} from "../types/devices.types";

// ── Devices ───────────────────────────────────────────────────────────────────

export const devicesService = {
  /** List all devices in the current org. */
  list(): Promise<Device[]> {
    return apiJSON<Device[]>("/api/devices/");
  },

  /** Get one device by ID. */
  get(deviceId: string): Promise<Device> {
    return apiJSON<Device>(`/api/devices/${deviceId}`);
  },

  /**
   * Create a one-time enrollment token.
   * Returns the raw token (shown once — user must copy it to the agent installer).
   */
  createEnrollmentToken(workspaceId?: string): Promise<EnrollmentToken> {
    return apiJSON<EnrollmentToken>("/api/devices/enroll-token", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId ?? null }),
    });
  },

  /** Revoke a device — it can no longer connect. */
  revokeDevice(deviceId: string): Promise<void> {
    return apiJSON<void>(`/api/devices/${deviceId}/revoke`, { method: "POST" });
  },

  /** Permanently delete a device record. */
  deleteDevice(deviceId: string): Promise<void> {
    return apiJSON<void>(`/api/devices/${deviceId}`, { method: "DELETE" });
  },

  /**
   * Rotate the device credential.
   * Returns the new raw credential (single-use display — must be installed on the device).
   */
  rotateCredential(deviceId: string): Promise<{ credential: string }> {
    return apiJSON<{ credential: string }>(
      `/api/devices/${deviceId}/rotate-credential`,
      { method: "POST" },
    );
  },
};

// ── Sessions ──────────────────────────────────────────────────────────────────

export const sessionsService = {
  /** List all control sessions in the current org. */
  list(): Promise<DeviceSession[]> {
    return apiJSON<DeviceSession[]>("/api/device-sessions/");
  },

  /** Get a single session. */
  get(sessionId: string): Promise<DeviceSession> {
    return apiJSON<DeviceSession>(`/api/device-sessions/${sessionId}`);
  },

  /** Create a new session (does NOT start it yet). */
  create(payload: CreateSessionPayload): Promise<DeviceSession> {
    return apiJSON<DeviceSession>("/api/device-sessions/", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /** Start a session — primary device takes control. */
  start(sessionId: string): Promise<DeviceSession> {
    return apiJSON<DeviceSession>(
      `/api/device-sessions/${sessionId}/start`,
      { method: "POST" },
    );
  },

  /** Stop a running session. */
  stop(sessionId: string): Promise<void> {
    return apiJSON<void>(
      `/api/device-sessions/${sessionId}/stop`,
      { method: "POST" },
    );
  },

  /** Update the device layout for a session. */
  updateLayout(sessionId: string, layout: LayoutEntry[]): Promise<void> {
    return apiJSON<void>(
      `/api/device-sessions/${sessionId}/layout`,
      {
        method: "PATCH",
        body: JSON.stringify({ layout }),
      },
    );
  },
};
