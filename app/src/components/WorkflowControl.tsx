import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import {
  workflowPause,
  workflowResume,
  workflowAbort,
  workflowApprove,
  workflowReject,
} from '@/hooks/useApi';
import WorkflowDAG from './WorkflowDAG';
import ArtifactsPanel from './ArtifactsPanel';
import { cn } from '@/lib/utils';
import { useWorkflowExecution } from '@/hooks/useApi';
import type { WorkflowExecutionDetail, TaskExecutionState, WorkflowEvent, WorkflowState } from '@/types';
import { Pause, Play, Square, CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react';

interface Props {
  progress: {
    state: WorkflowState;
    progress: number;
    current_task: string | null;
    completed_tasks: number;
    total_tasks: number;
    elapsed: number;
  };
  tasks: Array<Record<string, unknown>>;
  taskStates: Record<string, TaskExecutionState>;
  events?: WorkflowEvent[];
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}m ${secs}s`;
}

function StateBadge({ state }: { state: string }) {
  const variants: Record<string, { text: string; className: string; icon: React.ReactNode }> = {
    running: {
      text: 'Running',
      className: 'bg-emerald-900/40 text-emerald-300 border-emerald-700',
      icon: <Loader2 className="w-3 h-3 animate-spin" />,
    },
    paused: {
      text: 'Paused',
      className: 'bg-amber-900/40 text-amber-300 border-amber-700',
      icon: <Pause className="w-3 h-3" />,
    },
    waiting_approval: {
      text: 'Needs Approval',
      className: 'bg-rose-900/40 text-rose-300 border-rose-700',
      icon: <Clock className="w-3 h-3 animate-pulse" />,
    },
    completed: {
      text: 'Completed',
      className: 'bg-blue-900/40 text-blue-300 border-blue-700',
      icon: <CheckCircle className="w-3 h-3" />,
    },
    aborted: {
      text: 'Aborted',
      className: 'bg-red-900/40 text-red-300 border-red-700',
      icon: <Square className="w-3 h-3" />,
    },
    failed: {
      text: 'Failed',
      className: 'bg-red-900/40 text-red-300 border-red-700',
      icon: <XCircle className="w-3 h-3" />,
    },
  };

  const v = variants[state] || {
    text: state,
    className: 'bg-slate-800 text-slate-400 border-slate-700',
    icon: null,
  };

  return (
    <Badge variant="outline" className={`${v.className} flex items-center gap-1 text-xs`}>
      {v.icon}
      {v.text}
    </Badge>
  );
}

export default function WorkflowControl({ progress, tasks, taskStates, events }: Props) {
  const { execution } = useWorkflowExecution(events);
  const isRunning = progress.state === 'running';
  const isPaused = progress.state === 'paused';
  const needsApproval = progress.state === 'waiting_approval';
  const isCompleted = progress.state === 'completed';
  const isFailed = progress.state === 'failed';
  const isAborted = progress.state === 'aborted';
  const isFinished = isCompleted || isFailed || isAborted;

  return (
    <div className="bg-slate-800/50 border-b border-slate-700/80 px-5 py-3 max-h-[45vh] overflow-y-auto">
      {/* Top row: controls + status */}
      <div className="flex items-center justify-between mb-3 gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <h3 className="text-sm font-semibold text-slate-300 shrink-0">Workflow</h3>
          <StateBadge state={progress.state} />
          {progress.current_task && (
            <span className="text-xs text-slate-500 truncate">
              Task: <span className="text-slate-300">{progress.current_task}</span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-500 mr-1">
            {progress.completed_tasks}/{progress.total_tasks} tasks
            {progress.elapsed > 0 && ` · ${formatElapsed(progress.elapsed)}`}
          </span>
          {isFinished ? (
            <span className={`text-xs font-medium ${isCompleted ? 'text-blue-400' : isFailed ? 'text-red-400' : 'text-slate-400'}`}>
              {isCompleted ? 'All tasks finished' : isFailed ? 'Execution failed' : 'Aborted by user'}
            </span>
          ) : !needsApproval && (
            <>
              {isRunning ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-amber-700/60 text-amber-400 hover:bg-amber-900/25 h-7 text-xs px-2 transition-colors"
                  onClick={workflowPause}
                >
                  <Pause className="w-3.5 h-3.5 mr-1" /> Pause
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  className="border-emerald-700/60 text-emerald-400 hover:bg-emerald-900/25 h-7 text-xs px-2 transition-colors"
                  onClick={workflowResume}
                  disabled={!isPaused}
                >
                  <Play className="w-3.5 h-3.5 mr-1" /> Resume
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                className="border-red-700/60 text-red-400 hover:bg-red-900/25 h-7 text-xs px-2 transition-colors"
                onClick={workflowAbort}
              >
                <Square className="w-3.5 h-3.5 mr-1" /> Abort
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {progress.total_tasks > 0 && (
        <Progress
          value={progress.progress}
          className={cn(
            'h-1.5 transition-all',
            isCompleted
              ? '[&>div]:bg-blue-500 bg-slate-700'
              : isFailed || isAborted
                ? '[&>div]:bg-red-500 bg-slate-700'
                : isRunning
                  ? '[&>div]:bg-emerald-500 bg-slate-700'
                  : 'bg-slate-700 [&>div]:bg-amber-500',
          )}
        />
      )}

      {/* Approval panel */}
      {needsApproval && progress.current_task && (
        <div className="mt-3 p-3 bg-rose-900/20 border border-rose-700/50 rounded-lg flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-rose-400 animate-pulse shrink-0" />
            <span className="text-sm text-rose-300">
              Task <strong>&quot;{progress.current_task}&quot;</strong> requires approval
            </span>
          </div>
          <div className="flex gap-2 shrink-0">
            <Button
              size="sm"
              className="bg-emerald-700 hover:bg-emerald-600 text-white h-7 text-xs px-3 transition-colors"
              onClick={() => workflowApprove(progress.current_task!)}
            >
              <CheckCircle className="w-3.5 h-3.5 mr-1" /> Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="border-rose-700/60 text-rose-400 hover:bg-rose-900/25 h-7 text-xs px-3 transition-colors"
              onClick={() => workflowReject(progress.current_task!)}
            >
              <XCircle className="w-3.5 h-3.5 mr-1" /> Reject
            </Button>
          </div>
        </div>
      )}

      {/* Task list */}
      {tasks.length > 0 && (
        <div className="mt-3 flex gap-1.5 flex-wrap">
          {tasks.map((task, i) => {
            const taskName = task.name as string;
            const state = taskStates[taskName]?.state || 'pending';
            const stateColor = cn(
              state === 'running' && 'border-emerald-700/60 bg-emerald-900/20',
              state === 'completed' && 'border-blue-700/60 bg-blue-900/20',
              state === 'failed' && 'border-red-700/60 bg-red-900/20',
              state === 'pending' && 'border-slate-700 bg-slate-800/40',
              state === 'waiting_approval' && 'border-rose-700/60 bg-rose-900/20',
              state === 'paused' && 'border-amber-700/60 bg-amber-900/20',
            );
            return (
              <Badge
                key={i}
                variant="outline"
                className={`text-[10px] px-1.5 py-0.5 border ${stateColor} text-slate-300`}
              >
                {taskName}
              </Badge>
            );
          })}
        </div>
      )}

      {/* DAG + Artifacts side-by-side */}
      <div className="mt-3 grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="lg:col-span-2">
          <WorkflowDAG execution={execution} taskStates={taskStates} />
        </div>
        <div>
          <ArtifactsPanel execution={execution} taskStates={taskStates} />
        </div>
      </div>
    </div>
  );
}
