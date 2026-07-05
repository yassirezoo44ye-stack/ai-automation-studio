/**
 * WorkflowClient — frontend client for the WorkflowEngine.
 */
import { apiJSON } from "../../../shared/utils/api";

export interface WorkflowNodeDef {
  id:            string;
  node_type:     "start" | "end" | "task" | "condition" | "parallel" | "merge" | "checkpoint";
  config?:       Record<string, unknown>;
  next_nodes?:   string[];
  condition_map?: Record<string, string>;
  retry?:        number;
  timeout_s?:    number;
}

export interface WorkflowDefinition {
  id?:           string;
  name:          string;
  nodes:         Record<string, WorkflowNodeDef>;
  start_node_id: string;
  version?:      number;
}

export interface WorkflowExecution {
  execution_id:    string;
  workflow_id:     string;
  state:           "pending" | "running" | "completed" | "failed" | "paused";
  context:         Record<string, unknown>;
  completed_nodes: string[];
  current_node:    string | null;
  error:           string | null;
  started_at:      number;
  finished_at:     number | null;
}

export class WorkflowClient {
  async run(
    definition:      WorkflowDefinition,
    initialContext?: Record<string, unknown>,
  ): Promise<WorkflowExecution> {
    return apiJSON<WorkflowExecution>("/api/ai/workflows/run", {
      method: "POST",
      body:   JSON.stringify({ definition, context: initialContext ?? {} }),
    });
  }

  async resume(executionId: string, fromNodeId?: string): Promise<WorkflowExecution> {
    return apiJSON<WorkflowExecution>(`/api/ai/workflows/${executionId}/resume`, {
      method: "POST",
      body:   JSON.stringify({ from_node_id: fromNodeId }),
    });
  }

  async getExecution(executionId: string): Promise<WorkflowExecution> {
    return apiJSON<WorkflowExecution>(`/api/ai/workflows/${executionId}`);
  }
}

export const workflowClient = new WorkflowClient();
