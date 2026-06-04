import { useState, useEffect, useCallback, useRef } from 'react';
import type { AgentSummary, AgentDetail, SystemStatus, WorkflowEvent, WorkflowExecutionDetail, TaskExecutionState } from '@/types';

const API_BASE = '/api';

// ── 通用轮询 Hook ───────────────────────────────────────

function usePolling<T>(
  url: string,
  interval: number,
  parse: (json: unknown) => T,
  defaultValue: T,
) {
  const [data, setData] = useState<T>(defaultValue);
  const [error, setError] = useState<string | null>(null);
  const parseRef = useRef(parse);
  parseRef.current = parse;

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(url);
      if (!res.ok) {
        setError(`HTTP ${res.status}`);
        return;
      }
      setError(null);
      const json = await res.json();
      setData(parseRef.current(json));
    } catch (e) {
      setError(String(e));
    }
  }, [url]);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, interval);
    return () => clearInterval(id);
  }, [fetchData, interval]);

  return { data, error, refetch: fetchData };
}

// ── Agent 列表 ──────────────────────────────────────────

export function useAgents() {
  const { data, error, refetch } = usePolling<AgentSummary[]>(
    `${API_BASE}/agents`,
    5000,
    (json) => (json as Record<string, unknown>).agents as AgentSummary[] || [],
    [],
  );
  return { agents: data, error, refetch };
}

// ── Agent 详情 ──────────────────────────────────────────

export function useAgentDetail(agentId: string | null) {
  const [detail, setDetail] = useState<AgentDetail | null>(null);

  const fetchDetail = useCallback(async () => {
    if (!agentId) return;
    try {
      const res = await fetch(`${API_BASE}/agents/${encodeURIComponent(agentId)}`);
      if (!res.ok) return;
      const data = await res.json();
      if (!data.error) {
        setDetail(data);
      }
    } catch { /* silent */ }
  }, [agentId]);

  useEffect(() => {
    setDetail(null);
    if (!agentId) return;
    fetchDetail();
    const interval = setInterval(fetchDetail, 5000);
    return () => clearInterval(interval);
  }, [fetchDetail, agentId]);

  return { detail, refetch: fetchDetail };
}

// ── 系统状态 ────────────────────────────────────────────

export function useSystemStatus() {
  const { data, error, refetch } = usePolling<SystemStatus>(
    `${API_BASE}/status`,
    5000,
    (json) => json as SystemStatus,
    {
      agent_count: 0,
      agents: [],
      snapshot_count: 0,
      rule_engine_running: false,
    },
  );
  return { status: data, error, refetch };
}

// ── SSE 事件流 ──────────────────────────────────────────

export function useEventStream() {
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const maxEvents = 200;

  useEffect(() => {
    const evtSource = new EventSource(`${API_BASE}/events`);

    evtSource.onopen = () => setConnected(true);

    evtSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'heartbeat') return;
        data._id = `${data.type}_${data.timestamp}_${Math.random().toString(36).slice(2, 8)}`;
        setEvents(prev => {
          const updated = [data, ...prev];
          return updated.slice(0, maxEvents);
        });
      } catch {
        // ignore parse errors
      }
    };

    evtSource.onerror = () => setConnected(false);

    return () => evtSource.close();
  }, []);

  return { events, connected };
}

// ── 干预 / 快照 / 回滚 ──────────────────────────────────

export async function intervene(type: string, target: string, data?: Record<string, unknown>, reason?: string) {
  const res = await fetch(`${API_BASE}/intervene`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, target, data, reason }),
  });
  return safeJson(res);
}

export async function createSnapshot() {
  const res = await fetch(`${API_BASE}/snapshot`, { method: 'POST' });
  return safeJson(res);
}

export async function rollback(snapshotId: string) {
  const res = await fetch(`${API_BASE}/rollback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ snapshot_id: snapshotId }),
  });
  return safeJson(res);
}

export async function toggleRuleEngine(start: boolean, config?: Record<string, unknown>) {
  const res = await fetch(`${API_BASE}/rule_engine/${start ? 'start' : 'stop'}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: config ? JSON.stringify(config) : undefined,
  });
  return safeJson(res);
}

// ── Workflow 控制 ───────────────────────────────────────

export function useWorkflow(events?: WorkflowEvent[]) {
  const [tasks, setTasks] = useState<Array<Record<string, unknown>>>([]);
  const [progress, setProgress] = useState({
    state: 'none',
    progress: 0,
    current_task: null as string | null,
    completed_tasks: 0,
    total_tasks: 0,
    elapsed: 0,
  });
  const [taskStates, setTaskStates] = useState<Record<string, TaskExecutionState>>({});
  const lastEventCount = useRef(0);

  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/workflow/tasks`);
      if (!res.ok) return;
      const data = await res.json();
      setTasks(data.tasks || []);
    } catch { /* silent */ }
  }, []);

  const fetchProgress = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/workflow/progress`);
      if (!res.ok) return;
      const data = await res.json();
      setProgress({
        state: data.state || 'none',
        progress: data.progress || 0,
        current_task: data.current_task || null,
        completed_tasks: data.completed_tasks || 0,
        total_tasks: data.total_tasks || 0,
        elapsed: data.elapsed || 0,
      });
      if (data.task_execution_states) {
        setTaskStates(data.task_execution_states as Record<string, TaskExecutionState>);
      }
    } catch { /* silent */ }
  }, []);

  // SSE 事件驱动即时刷新 — 修复负数 slice 风险
  useEffect(() => {
    if (!events) return;
    const newCount = events.length;
    const oldCount = lastEventCount.current;
    if (newCount <= oldCount) {
      lastEventCount.current = newCount;
      return;
    }
    const newEvents = events.slice(0, newCount - oldCount);
    lastEventCount.current = newCount;
    const hasWorkflowEvent = newEvents.some(
      (e) => e.type === 'workflow_state_change' || e.type === 'task_started' || e.type === 'task_completed'
    );
    if (hasWorkflowEvent) {
      fetchTasks();
      fetchProgress();
    }
  }, [events, fetchTasks, fetchProgress]);

  useEffect(() => {
    fetchTasks();
    fetchProgress();
    const interval = setInterval(() => {
      fetchTasks();
      fetchProgress();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchTasks, fetchProgress]);

  return { tasks, progress, taskStates, refetch: () => { fetchTasks(); fetchProgress(); } };
}

export function useWorkflowExecution(events?: WorkflowEvent[]) {
  const [execution, setExecution] = useState<WorkflowExecutionDetail | null>(null);
  const lastEventCount = useRef(0);

  const fetchExecution = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/workflow/execution`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.defined) {
        setExecution(data as WorkflowExecutionDetail);
      } else {
        setExecution(null);
      }
    } catch {
      setExecution(null);
    }
  }, []);

  // SSE 事件驱动即时刷新 — 修复负数 slice 风险
  useEffect(() => {
    if (!events) return;
    const newCount = events.length;
    const oldCount = lastEventCount.current;
    if (newCount <= oldCount) {
      lastEventCount.current = newCount;
      return;
    }
    const newEvents = events.slice(0, newCount - oldCount);
    lastEventCount.current = newCount;
    const hasWorkflowEvent = newEvents.some(
      (e) => e.type === 'workflow_state_change' || e.type === 'task_started' || e.type === 'task_completed'
    );
    if (hasWorkflowEvent) {
      fetchExecution();
    }
  }, [events, fetchExecution]);

  useEffect(() => {
    fetchExecution();
    const interval = setInterval(fetchExecution, 5000);
    return () => clearInterval(interval);
  }, [fetchExecution]);

  return { execution, refetch: fetchExecution };
}

// ── Workflow 操作 ───────────────────────────────────────

export async function workflowPause() {
  const res = await fetch(`${API_BASE}/workflow/pause`, { method: 'POST' });
  return safeJson(res);
}

export async function workflowResume() {
  const res = await fetch(`${API_BASE}/workflow/resume`, { method: 'POST' });
  return safeJson(res);
}

export async function workflowAbort() {
  const res = await fetch(`${API_BASE}/workflow/abort`, { method: 'POST' });
  return safeJson(res);
}

export async function workflowApprove(taskName: string) {
  const res = await fetch(`${API_BASE}/workflow/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_name: taskName }),
  });
  return safeJson(res);
}

export async function workflowReject(taskName: string) {
  const res = await fetch(`${API_BASE}/workflow/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_name: taskName }),
  });
  return safeJson(res);
}

// ── Safe JSON parse ─────────────────────────────────────

async function safeJson(res: Response): Promise<Record<string, unknown>> {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    console.error('[API] Non-JSON response:', text.slice(0, 200));
    return {
      error: `Server error (HTTP ${res.status}). Is the API server running?`,
      _raw: text.slice(0, 500),
    };
  }
}

// ── v3.1: Workflow 定义与启动 ──────────────────────────

export interface TaskDef {
  name: string;
  description: string;
  expected_output?: string;
  agent_id?: string;
  requires_approval?: boolean;
  max_retries?: number;
  temperature?: number;
  review_gate?: string;
  max_passes?: number;
  allowed_tools?: string[];
}

export interface EdgeDef {
  from: string;
  to: string;
}

export async function workflowDefine(
  name: string,
  tasks: TaskDef[],
  edges: EdgeDef[],
  mode: string = 'fixed',
) {
  const res = await fetch(`${API_BASE}/workflow/define`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, tasks, edges, mode }),
  });
  return safeJson(res);
}

export async function workflowStart(apiKey?: string) {
  const res = await fetch(`${API_BASE}/workflow/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(apiKey ? { api_key: apiKey } : {}),
  });
  return safeJson(res);
}

// ── v3.1: Agent 注册 ────────────────────────────────────

export async function agentRegister(config: {
  agent_id: string;
  api_key?: string;
  model?: string;
  temperature?: number;
  max_iterations?: number;
  system_prompt?: string;
  workflow_name?: string;
}) {
  const res = await fetch(`${API_BASE}/agent/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  return safeJson(res);
}

export async function fetchAgentTemplates() {
  const res = await fetch(`${API_BASE}/agent/templates`);
  return res.json();
}

// ── v3.1: React hooks ───────────────────────────────────

export function useAgentTemplates() {
  const [templates, setTemplates] = useState<{
    llm_providers: Array<{
      id: string;
      name: string;
      default_model: string;
      models: string[];
    }>;
    defaults: Record<string, number>;
    task_presets: Array<{
      id: string;
      name: string;
      description: string;
    }>;
  } | null>(null);

  useEffect(() => {
    fetchAgentTemplates().then(setTemplates).catch(() => {});
  }, []);

  return templates;
}
