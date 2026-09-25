export type CreationType =
  | "APP"
  | "AGENT"
  | "WORKFLOW"
  | "AUTOMATION"
  | "TEMPLATE"
  | "DEVICE_WORKFLOW";

export type Visibility = "private" | "public";

export interface FlowCreation {
  id: string;
  organization_id: string;
  created_by_user_id: string | null;
  type: CreationType;
  title: string;
  description: string | null;
  visibility: Visibility;
  source_type: string | null;
  source_id: string | null;
  thumbnail_url: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
  user_liked?: boolean;
  user_saved?: boolean;
}

export interface CreateCreationPayload {
  type: CreationType;
  title: string;
  description?: string;
  visibility?: Visibility;
  source_type?: string;
  source_id?: string;
  thumbnail_url?: string;
  tags?: string[];
}

export interface UpdateCreationPayload {
  title?: string;
  description?: string;
  thumbnail_url?: string;
  tags?: string[];
}

export interface CreationFeedResponse {
  items: FlowCreation[];
  total: number;
}
