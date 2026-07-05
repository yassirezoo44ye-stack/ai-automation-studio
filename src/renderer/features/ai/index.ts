// Public surface of the AI feature
export { AIWorkspace } from "./AIWorkspace";
// Services are consumed by components internally — not re-exported to avoid name collisions
// Consumers import directly: import { fetchAgents } from "@features/ai/agents/agentService"
