export interface AgentSummary {
  agent_id: string;
  message_count: number;
  step_count: number;
  total_usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  snapshots: number;
  last_message: Record<string, unknown> | null;
  metadata?: Record<string, unknown>;
}

export type MessageRole = 'system' | 'user' | 'assistant' | 'tool';

export interface Message {
  role: MessageRole;
  content: string | null;
  tool_calls?: Array<{
    id: string;
    type: string;
    function: {
      name: string;
      arguments: string;
    };
  }>;
  tool_call_id?: string | null;
  name?: string | null;
}

export interface StepRecord {
  step_id: string;
  iteration: number;
  timestamp: number;
  thought: string | null;
  action: Record<string, unknown> | null;
  observation: string | null;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  } | null;
  intervention: Record<string, unknown> | null;
}

export interface AgentDetail {
  agent_id: string;
  summary: AgentSummary;
  messages: Message[];
  steps: StepRecord[];
  snapshots: Array<{
    snapshot_id: string;
    timestamp: number;
    message_count: number;
    step_count: number;
    metadata: Record<string, unknown>;
  }>;
  transcript: string;
}

export type WorkflowEventType =
  | 'agent_registered'
  | 'agent_unregistered'
  | 'message_added'
  | 'system_updated'
  | 'step_recorded'
  | 'snapshot_created'
  | 'rollback'
  | 'intervention'
  | 'agent_to_agent'
  | 'workflow_state_change'
  | 'workflow_complete'
  | 'workflow_error'
  | 'task_started'
  | 'task_completed'
  | 'heartbeat';

export interface WorkflowEvent {
  type: WorkflowEventType;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface SystemStatus {
  agent_count: number;
  agents: string[];
  snapshot_count: number;
  rule_engine_running: boolean;
}

// ── Workflow Execution Types ─────────────────────────────

export type TaskState =
  | 'pending'
  | 'running'
  | 'waiting_approval'
  | 'approved'
  | 'rejected'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'recovered';

export interface TaskExecutionState {
  state: TaskState;
  agent_id: string;
  elapsed: number;
  error: string | null;
  retry_count: number;
  artifacts: string[];
}

export interface TaskExecutionDetail {
  task_name: string;
  state: TaskState;
  output: string;
  agent_id: string;
  elapsed: number;
  started_at: number | null;
  completed_at: number | null;
  error: string | null;
  retry_count: number;
  artifacts: string[];
}

export type WorkflowState =
  | 'none'
  | 'pending'
  | 'running'
  | 'paused'
  | 'waiting_approval'
  | 'waiting_recovery'
  | 'completed'
  | 'failed'
  | 'aborted';

export interface WorkflowExecutionDetail {
  defined: boolean;
  workflow_id: string | null;
  name: string | null;
  state: WorkflowState;
  tasks: Array<{
    name: string;
    agent_id: string;
    requires_approval: boolean;
    timeout: number | null;
    max_retries: number;
    temperature: number | null;
    parallel: boolean;
    has_local_executor: boolean;
  }>;
  edges: Array<{ from: string; to: string }>;
  task_executions: Record<string, TaskExecutionDetail>;
  execution_order: string[];
  total_elapsed: number;
  error: string | null;
}

export interface ArtifactInfo {
  path: string;
  name: string;
  task_name: string;
  agent_id: string;
}
