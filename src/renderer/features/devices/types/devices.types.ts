/** Frontend types for the Multi-Device Control feature. */

export type DeviceStatus =
  | "online"
  | "offline"
  | "connecting"
  | "revoked"
  | "control_active"
  | "control_disabled";

export interface Device {
  id: string;
  organization_id: string;
  workspace_id: string | null;
  created_by: string | null;
  name: string;
  platform: "windows" | "macos" | "linux" | "unknown";
  hostname: string | null;
  agent_version: string | null;
  status: DeviceStatus;
  screen_width: number | null;
  screen_height: number | null;
  screen_position: { x: number; y: number };
  display_config: DisplayInfo[];
  capabilities: Record<string, unknown>;
  registered_at: string;
  last_seen_at: string | null;
  last_connected_at: string | null;
}

export interface DisplayInfo {
  x: number;
  y: number;
  width: number;
  height: number;
  is_primary: boolean;
  name?: string;
}

export interface EnrollmentToken {
  enrollment_token: string;
  token_prefix: string;
  expires_at: string;
  workspace_id: string | null;
}

export type SessionStatus = "draft" | "starting" | "active" | "stopping" | "stopped" | "expired" | "failed";

export interface DeviceSession {
  id: string;
  organization_id: string;
  workspace_id: string | null;
  created_by: string | null;
  primary_device_id: string;
  status: SessionStatus;
  name: string | null;
  started_at: string | null;
  stopped_at: string | null;
  stop_reason: string | null;
  created_at: string;
  updated_at: string;
  members: SessionMember[];
}

export interface SessionMember {
  id: string;
  device_id: string;
  session_id: string;
  is_primary: boolean;
  position_x: number;
  position_y: number;
  width: number;
  height: number;
  enabled: boolean;
}

export interface LayoutEntry {
  device_id: string;
  position_x: number;
  position_y: number;
  width: number;
  height: number;
  enabled: boolean;
}

export interface CreateSessionPayload {
  primary_device_id: string;
  device_ids: string[];
  workspace_id?: string;
}
