export type FactoryPhase =
  | "IDEA"
  | "BLUEPRINT"
  | "BUILDING"
  | "TESTING"
  | "VERIFYING"
  | "DEPLOYING"
  | "LIVE"
  | "FAILED"
  | "CANCELLED";

export interface PhaseCheckpoint {
  [phaseName: string]: Record<string, unknown>;
}

export interface FactoryProject {
  id: string;
  idea_text: string;
  phase: FactoryPhase;
  checkpoint: PhaseCheckpoint;
  app_builder_app_id: string | null;
  flow_creation_id: string | null;
  error_message: string | null;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface SubmitIdeaResponse {
  project_id: string;
  phase: FactoryPhase;
  message: string;
}

export interface ListProjectsResponse {
  projects: FactoryProject[];
}
