import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import type { WorkflowExecutionDetail, TaskExecutionState } from '@/types';
import { cn } from '@/lib/utils';
import {
  GitBranch,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  SkipForward,
  AlertTriangle,
  Package,
  CircleDot,
  ShieldCheck,
  ShieldAlert,
  RefreshCw,
} from 'lucide-react';

interface Props {
  execution?: WorkflowExecutionDetail | null;
  taskStates?: Record<string, TaskExecutionState>;
  /** 预览模式：只展示 DAG 结构，不展示执行状态 */
  preview?: boolean;
  /** 预览模式下传入的 tasks 和 edges */
  previewTasks?: Array<{ name: string; agent_id: string; requires_approval?: boolean; review_gate?: string | null; max_passes?: number }>;
  previewEdges?: Array<{ from: string; to: string }>;
  /** Review gate edges: reviewer -> implement task */
  reviewEdges?: Array<{ from: string; to: string }>;
  /** Review results per task */
  reviewResults?: Record<string, { approved: boolean; feedback: string; pass_num: number }>;

}

const stateConfig: Record<
  string,
  { color: string; bg: string; border: string; icon: React.ReactNode }
> = {
  completed: {
    color: 'text-emerald-400',
    bg: 'bg-emerald-900/30',
    border: 'border-emerald-700/60',
    icon: <CheckCircle2 className="w-3.5 h-3.5" />,
  },
  recovered: {
    color: 'text-emerald-400',
    bg: 'bg-emerald-900/30',
    border: 'border-emerald-700/60',
    icon: <CheckCircle2 className="w-3.5 h-3.5" />,
  },
  running: {
    color: 'text-cyan-400',
    bg: 'bg-cyan-900/30',
    border: 'border-cyan-600/60',
    icon: <Loader2 className="w-3.5 h-3.5 animate-spin" />,
  },
  failed: {
    color: 'text-red-400',
    bg: 'bg-red-900/30',
    border: 'border-red-700/60',
    icon: <XCircle className="w-3.5 h-3.5" />,
  },
  waiting_approval: {
    color: 'text-rose-400',
    bg: 'bg-rose-900/30',
    border: 'border-rose-700/60',
    icon: <Clock className="w-3.5 h-3.5 animate-pulse" />,
  },
  approved: {
    color: 'text-emerald-400',
    bg: 'bg-emerald-900/20',
    border: 'border-emerald-700/40',
    icon: <CheckCircle2 className="w-3.5 h-3.5" />,
  },
  rejected: {
    color: 'text-red-400',
    bg: 'bg-red-900/20',
    border: 'border-red-700/40',
    icon: <XCircle className="w-3.5 h-3.5" />,
  },
  skipped: {
    color: 'text-slate-400',
    bg: 'bg-slate-800/50',
    border: 'border-slate-600/40',
    icon: <SkipForward className="w-3.5 h-3.5" />,
  },
  pending: {
    color: 'text-slate-500',
    bg: 'bg-slate-800/30',
    border: 'border-slate-700/40',
    icon: <CircleDot className="w-3.5 h-3.5" />,
  },
};

function getStateStyle(state: string) {
  return (
    stateConfig[state] || {
      color: 'text-slate-400',
      bg: 'bg-slate-800/30',
      border: 'border-slate-700/40',
      icon: <CircleDot className="w-3.5 h-3.5" />,
    }
  );
}

function formatTime(seconds: number): string {
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}m ${secs}s`;
}

// Compute topological layers for DAG layout
function computeLayers(tasks: string[], edges: Array<{ from: string; to: string }>): string[][] {
  const inDegree: Record<string, number> = {};
  const adj: Record<string, string[]> = {};
  for (const t of tasks) {
    inDegree[t] = 0;
    adj[t] = [];
  }
  for (const e of edges) {
    if (adj[e.from]) {
      adj[e.from].push(e.to);
      inDegree[e.to] = (inDegree[e.to] || 0) + 1;
    }
  }

  const layers: string[][] = [];
  while (true) {
    const layer = Object.entries(inDegree).filter(([, d]) => d === 0).map(([n]) => n);
    if (layer.length === 0) break;
    layers.push(layer);
    for (const node of layer) {
      inDegree[node] = -1;
      for (const neighbor of adj[node] || []) {
        if (inDegree[neighbor] >= 0) {
          inDegree[neighbor] -= 1;
        }
      }
    }
  }
  return layers;
}

function TaskNode({
  task,
  exec,
  onClick,
  isSelected,
  isReviewer,
  reviewResult,
}: {
  task: { name: string; agent_id: string; requires_approval: boolean; review_gate?: string | null; max_passes?: number };
  exec: TaskExecutionState | undefined;
  onClick: () => void;
  isSelected: boolean;
  isReviewer?: boolean;
  reviewResult?: { approved: boolean; feedback: string; pass_num: number } | null;
}) {
  const isPreview = !exec;
  const state = exec?.state || 'pending';
  const style = isPreview
    ? { color: 'text-slate-400', bg: 'bg-slate-800/40', border: 'border-slate-700/50', icon: <CircleDot className="w-3.5 h-3.5" /> }
    : getStateStyle(state);

  return (
    <button
      onClick={onClick}
      className={`relative flex flex-col items-start p-2.5 rounded-lg border transition-all w-[150px] text-left ${
        isSelected ? 'ring-1 ring-cyan-400 ring-offset-1 ring-offset-slate-900' : ''
      } ${style.bg} ${style.border} hover:brightness-110`}
    >
      <div className="flex items-center gap-1.5 w-full min-w-0">
        <span className={cn(style.color, 'shrink-0')}>{style.icon}</span>
        <span className="text-xs font-medium text-slate-200 truncate">{task.name}</span>
      </div>
      <div className="flex items-center gap-1.5 mt-1 w-full min-w-0">
        <span className="text-[10px] text-slate-500 truncate">{task.agent_id || '—'}</span>
        {task.requires_approval && (
          <span className="text-[10px] text-amber-400 shrink-0">*</span>
        )}
        {isReviewer && (
          <span className="text-[10px] text-purple-400 shrink-0 flex items-center gap-0.5" title="Reviewer">
            <ShieldCheck className="w-3 h-3" />
          </span>
        )}
        {task.review_gate && (
          <span className="text-[10px] text-orange-400 shrink-0" title={`Reviewed by ${task.review_gate}`}>
            R
          </span>
        )}
      </div>
      {exec && exec.elapsed > 0 && (
        <div className="text-[10px] text-slate-500 mt-0.5">{formatTime(exec.elapsed)}</div>
      )}
      {exec && exec.error && (
        <div className="text-[10px] text-red-400 mt-0.5 truncate w-full">{exec.error}</div>
      )}
      {exec && exec.artifacts.length > 0 && (
        <div className="flex items-center gap-1 mt-1 text-[10px] text-cyan-400">
          <Package className="w-3 h-3" />
          {exec.artifacts.length}
        </div>
      )}
      {/* Review result badge */}
      {reviewResult && (
        <div className={`mt-1 text-[10px] flex items-center gap-1 px-1.5 py-0.5 rounded ${
          reviewResult.approved
            ? 'bg-emerald-900/40 text-emerald-400'
            : 'bg-red-900/40 text-red-400'
        }`}>
          {reviewResult.approved ? <ShieldCheck className="w-3 h-3" /> : <ShieldAlert className="w-3 h-3" />}
          {reviewResult.approved ? 'Approved' : `Rejected #${reviewResult.pass_num}`}
        </div>
      )}
      {/* Retry count */}
      {exec && exec.retry_count > 0 && (
        <div className="flex items-center gap-1 mt-1 text-[10px] text-amber-400">
          <RefreshCw className="w-3 h-3" />
          Retried {exec.retry_count}x
        </div>
      )}
    </button>
  );
}

export default function WorkflowDAG({
  execution,
  taskStates = {},
  preview = false,
  previewTasks = [],
  previewEdges = [],
}: Props) {
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(true);

  // 预览模式 vs 执行模式的数据源
  const isPreview = preview || !execution;
  const tasks = isPreview ? previewTasks : execution?.tasks || [];
  const edges = isPreview ? previewEdges : execution?.edges || [];
  const taskExecutions = isPreview ? {} : execution?.task_executions || {};
  const workflowId = isPreview ? '' : execution?.workflow_id;

  // Compute which tasks are reviewers (some task's review_gate points to them)
  const reviewerTasks = useMemo(() => {
    const set = new Set<string>();
    for (const t of tasks) {
      if (t.review_gate) set.add(t.review_gate);
    }
    return set;
  }, [tasks]);

  // Parse review results from task execution outputs
  const reviewResults = useMemo(() => {
    const results: Record<string, { approved: boolean; feedback: string; pass_num: number }> = {};
    for (const [name, exec] of Object.entries(taskExecutions)) {
      if (!exec.output) continue;
      try {
        const data = JSON.parse(exec.output);
        if (data._review_decision) {
          results[name] = {
            approved: data._review_decision.approved,
            feedback: data._review_decision.feedback || '',
            pass_num: data._review_decision.pass_num || 1,
          };
        }
      } catch {
        // Not JSON, skip
      }
    }
    return results;
  }, [taskExecutions]);

  const layers = useMemo(() => {
    const taskNames = tasks.map((t) => t.name);
    return computeLayers(taskNames, edges);
  }, [tasks, edges]);

  if (tasks.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-slate-500 text-sm">
        <GitBranch className="w-5 h-5 mr-2 text-slate-600 shrink-0" />
        No workflow defined
      </div>
    );
  }

  const taskMap = new Map(tasks.map((t) => [t.name, t]));
  const selectedExec = selectedTask ? taskExecutions[selectedTask] : null;

  return (
    <Card className="bg-slate-800/40 border-slate-700/60">
      <CardHeader className="py-2.5 px-4">
        <CardTitle className="text-xs flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <GitBranch className="w-4 h-4 text-slate-400 shrink-0" />
            <span className="text-slate-300 truncate">{isPreview ? 'DAG Preview' : 'Workflow DAG'}</span>
            {workflowId && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-slate-700/50 text-slate-400 border-slate-600 shrink-0">
                {workflowId}
              </Badge>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-1 text-slate-500 hover:text-slate-300 shrink-0"
            onClick={() => setShowDetail(!showDetail)}
          >
            {showDetail ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </Button>
        </CardTitle>
      </CardHeader>

      {showDetail && (
        <CardContent className="px-4 pb-4 pt-0">
          <ScrollArea className="max-h-[280px]">
            {/* DAG Layout */}
            <div className="flex flex-col items-center gap-4 py-2">
              {layers.map((layer, li) => (
                <div key={li} className="flex flex-wrap justify-center gap-3">
                  {layer.map((taskName) => {
                    const task = taskMap.get(taskName);
                    if (!task) return null;
                    return (
                      <TaskNode
                        key={taskName}
                        task={task}
                        exec={!isPreview ? (taskStates[taskName] || taskExecutions[taskName]) : undefined}
                        onClick={() => setSelectedTask(selectedTask === taskName ? null : taskName)}
                        isSelected={selectedTask === taskName}
                        isReviewer={reviewerTasks.has(taskName)}
                        reviewResult={reviewResults[taskName] || null}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </ScrollArea>

          {/* Selected task detail */}
          {selectedTask && selectedExec && !isPreview && (
            <div className="mt-3 p-3 rounded-lg bg-slate-900/50 border border-slate-700/50">
              <div className="flex items-center justify-between mb-2 gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-xs font-medium text-slate-200 truncate">{selectedTask}</span>
                  <Badge variant="outline" className={`text-[10px] px-1.5 py-0 shrink-0 ${getStateStyle(selectedExec.state).bg} ${getStateStyle(selectedExec.state).color} ${getStateStyle(selectedExec.state).border}`}>
                    {selectedExec.state}
                  </Badge>
                </div>
                <span className="text-[10px] text-slate-500 shrink-0">
                  {selectedExec.elapsed > 0 ? formatTime(selectedExec.elapsed) : '—'}
                </span>
              </div>
              {selectedExec.output && (
                <div className="text-xs text-slate-400 font-mono bg-slate-800/50 rounded p-2 max-h-24 overflow-auto whitespace-pre-wrap break-words">
                  {selectedExec.output.length > 500 ? selectedExec.output.slice(0, 500) + '...' : selectedExec.output}
                </div>
              )}
              {selectedExec.error && (
                <div className="flex items-start gap-1.5 mt-2 text-xs text-red-400">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span className="break-words">{selectedExec.error}</span>
                </div>
              )}
              {selectedExec.artifacts.length > 0 && (
                <div className="mt-2 space-y-1">
                  <div className="text-[10px] text-slate-500 font-medium">Artifacts</div>
                  {selectedExec.artifacts.map((art, i) => (
                    <div key={i} className="flex items-center gap-1.5 text-xs text-cyan-400">
                      <Package className="w-3 h-3 shrink-0" />
                      <span className="font-mono truncate">{art}</span>
                    </div>
                  ))}
                </div>
              )}
              {selectedExec.retry_count > 0 && (
                <div className="text-[10px] text-amber-400 mt-1">
                  Retried {selectedExec.retry_count} time(s)
                </div>
              )}
              {/* Show review result if available */}
              {selectedTask && reviewResults[selectedTask] && (
                <div className={`mt-2 p-2 rounded text-xs ${
                  reviewResults[selectedTask].approved
                    ? 'bg-emerald-900/20 border border-emerald-700/40'
                    : 'bg-red-900/20 border border-red-700/40'
                }`}
                >
                  <div className="flex items-center gap-1.5 font-medium mb-1">
                    {reviewResults[selectedTask].approved ? (
                      <>
                        <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                        <span className="text-emerald-400">Review Approved</span>
                      </>
                    ) : (
                      <>
                        <ShieldAlert className="w-3.5 h-3.5 text-red-400" />
                        <span className="text-red-400">Review Rejected (Pass #{reviewResults[selectedTask].pass_num})</span>
                      </>
                    )}
                  </div>
                  {reviewResults[selectedTask].feedback && (
                    <div className="text-slate-400 whitespace-pre-wrap break-words max-h-24 overflow-auto">
                      {reviewResults[selectedTask].feedback}
                    </div>
                  )}
                </div>
              )}
              {/* Show review_gate info */}
              {selectedTask && taskMap.get(selectedTask)?.review_gate && (
                <div className="mt-2 text-[10px] text-orange-400 flex items-center gap-1">
                  <ShieldCheck className="w-3 h-3" />
                  Reviewed by: {taskMap.get(selectedTask)?.review_gate}
                </div>
              )}
            </div>
          )}

          {/* Legend */}
          {!isPreview && (
            <div className="flex flex-wrap gap-2 mt-3">
              {['pending', 'running', 'completed', 'failed', 'waiting_approval', 'skipped'].map((s) => {
                const cfg = getStateStyle(s);
                return (
                  <div key={s} className="flex items-center gap-1 text-[10px] text-slate-500">
                    <span className={cfg.color}>{cfg.icon}</span>
                    <span className="capitalize">{s.replace('_', ' ')}</span>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
