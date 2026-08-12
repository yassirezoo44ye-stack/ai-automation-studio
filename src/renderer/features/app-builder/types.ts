// Types for the AI Business App Builder feature.

export interface ColumnDef {
  name: string;
  type: string;
  nullable: boolean;
  unique: boolean;
}

export interface RelationshipDef {
  kind: "belongs_to" | "has_many";
  target: string;
}

export interface EntityDef {
  name: string;
  display_name: string;
  columns: ColumnDef[];
  relationships: RelationshipDef[];
}

export interface PageDef {
  name: string;
  entity: string | null;
  kind: "list" | "detail" | "dashboard" | "form";
}

export interface RoleDef {
  name: string;
  permissions: string[];
}

export interface WorkflowDef {
  name: string;
  trigger: string;
}

export interface AgentDef {
  name: string;
  description: string;
}

export interface AppSpec {
  name: string;
  description: string;
  target_users: string;
  entities: EntityDef[];
  pages: PageDef[];
  roles: RoleDef[];
  workflows: WorkflowDef[];
  agents: AgentDef[];
  integrations: string[];
}

export interface BuildStep {
  label: string;
  status: "ok" | "warning" | "error" | "pending";
  detail: string;
}

export interface BuildSummary {
  tables: number;
  pages: number;
  roles: number;
  api_operations: number;
  workflows: number;
  agents: number;
  canvas_id: string | null;
}

export interface BuildResult {
  app_id: string;
  app_name: string;
  status: "ready" | "partial" | "failed";
  summary: BuildSummary;
  steps: BuildStep[];
  warnings: string[];
}

export interface AppVersion {
  version_number: number;
  label: string;
  change_summary: string | null;
  created_at: string;
}

export interface AppRecord {
  id: string;
  name: string;
  description: string | null;
  build_status: "pending" | "planning" | "building" | "ready" | "failed";
  include_automation: boolean;
  workflow_count: number;
  agent_count: number;
  created_at: string;
  updated_at: string;
}

export interface AppDetail extends AppRecord {
  spec: AppSpec;
  build_result: Partial<BuildSummary & { steps: BuildStep[] }>;
  build_warnings: string[];
  canvas_id: string | null;
  versions: AppVersion[];
}

export type BuildPhase =
  | "idle"
  | "previewing"
  | "building"
  | "done"
  | "error";
