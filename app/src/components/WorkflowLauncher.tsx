import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  workflowStart,
  workflowPause,
  workflowResume,
  workflowAbort,
  useWorkflowDefinition,
} from '@/hooks/useApi';
import { useWorkflow } from '@/hooks/useApi';
import {
  Play,
  Pause,
  Square,
  RotateCw,
  Loader2,
  Key,
  ChevronDown,
  ChevronUp,
  Clock,
  CheckCircle2,
  XCircle,
  FileText,
} from 'lucide-react';

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}m ${secs}s`;
}

interface ExecutionRun {
  run_id: string;
  workflow_name: string;
  workflow_id: string;
  started_at: number;
  total_elapsed: number;
  success: boolean;
  task_count: number;
  completed_count: number;
  report_path: string;
}

export default function WorkflowLauncher() {
  const { definition } = useWorkflowDefinition();
  const { progress } = useWorkflow();
  const [apiKey, setApiKey] = useState('');
  const [starting, setStarting] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<ExecutionRun[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const hasDefinition = definition?.defined && definition?.workflow;
  const isRunning = progress.state === 'running';
  const isPaused = progress.state === 'paused';
  const isIdle = progress.state === 'none' || progress.state === 'completed' || progress.state === 'aborted' || progress.state === 'failed';

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await fetch('/api/workflow/history');
      if (res.ok) {
        const data = await res.json();
        setHistory(data.runs || []);
      }
    } catch {
      // ignore
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    if (showHistory) {
      fetchHistory();
    }
  }, [showHistory, fetchHistory]);

  // Refresh history when workflow completes
  useEffect(() => {
    if (progress.state === 'completed' || progress.state === 'failed') {
      fetchHistory();
    }
  }, [progress.state, fetchHistory]);

  const handleStart = async () => {
    setStarting(true);
    setStatusMsg('');
    try {
      const res = await workflowStart(apiKey || undefined);
      if (res.error) {
        setStatusMsg(String(res.error));
      } else {
        setStatusMsg(String(res.message || 'Workflow started'));
      }
    } catch {
      setStatusMsg('Failed to start workflow');
    } finally {
      setStarting(false);
    }
  };

  const handlePause = async () => {
    await workflowPause();
    setStatusMsg('Paused');
  };

  const handleResume = async () => {
    await workflowResume();
    setStatusMsg('Resumed');
  };

  const handleAbort = async () => {
    await workflowAbort();
    setStatusMsg('Aborted');
  };

  const getStateBadge = () => {
    if (!hasDefinition) return null;
    const mapping: Record<string, { label: string; className: string }> = {
      running: { label: 'Running', className: 'bg-emerald-900/40 text-emerald-300 border-emerald-700' },
      paused: { label: 'Paused', className: 'bg-amber-900/40 text-amber-300 border-amber-700' },
      waiting_approval: { label: 'Waiting Approval', className: 'bg-rose-900/40 text-rose-300 border-rose-700' },
      completed: { label: 'Completed', className: 'bg-emerald-900/40 text-emerald-300 border-emerald-700' },
      failed: { label: 'Failed', className: 'bg-red-900/40 text-red-300 border-red-700' },
      aborted: { label: 'Aborted', className: 'bg-red-900/40 text-red-300 border-red-700' },
      none: { label: 'Idle', className: 'bg-slate-800 text-slate-400 border-slate-700' },
    };
    const s = mapping[progress.state] || { label: progress.state, className: 'bg-slate-800 text-slate-400 border-slate-700' };
    return (
      <Badge variant="outline" className={`text-xs ${s.className}`}>
        {s.label}
      </Badge>
    );
  };

  return (
    <div className="flex flex-col"
    >
      {/* Top bar: status + controls */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700/80 bg-slate-800/50"
      >
        <div className="flex items-center gap-2"
        >
          <Play className="w-4 h-4 text-emerald-400" />
          <h2 className="text-sm font-semibold text-slate-200"
          >Launcher</h2>
          {getStateBadge()}
        </div>
        {progress.total_tasks > 0 && (
          <span className="text-xs text-slate-400"
          >
            {progress.completed_tasks}/{progress.total_tasks}
            {progress.elapsed > 0 && ` · ${formatElapsed(progress.elapsed)}`}
          </span>
        )}
      </div>

      <div className="px-4 py-3 space-y-3"
      >
        {/* Definition Status */}
        {!hasDefinition ? (
          <p className="text-xs text-slate-500 text-center py-2"
          >
            Define a workflow in the Builder panel first
          </p>
        ) : (
          <>
            {/* Progress */}
            {progress.total_tasks > 0 && (
              <div className="space-y-1"
              >
                <div className="flex justify-between text-[10px] text-slate-500"
                >
                  <span>Progress</span>
                  <span>{Math.round(progress.progress)}%</span>
                </div>
                <Progress value={progress.progress} className="h-1.5 bg-slate-700" />
                {progress.current_task && (
                  <p className="text-[10px] text-slate-500"
                  >
                    Current: <span className="text-slate-300">{progress.current_task}</span>
                  </p>
                )}
              </div>
            )}

            {/* API Key */}
            {isIdle && (
              <div className="space-y-1"
              >
                <Label className="text-xs text-slate-400 flex items-center gap-1"
                >
                  <Key className="w-3 h-3" /> API Key
                </Label>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={e => setApiKey(e.target.value)}
                  placeholder="Leave blank to use .env"
                  className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8 placeholder:text-slate-600"
                />
              </div>
            )}

            {/* Controls */}
            <div className="flex gap-2"
            >
              {isIdle && (
                <Button
                  className="flex-1 bg-emerald-700 hover:bg-emerald-600 text-white h-8 text-xs transition-colors"
                  onClick={handleStart}
                  disabled={starting}
                >
                  {starting ? (
                    <><Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> Starting</>
                  ) : (
                    <><Play className="w-3.5 h-3.5 mr-1" /> Start Workflow</>
                  )}
                </Button>
              )}

              {isRunning && (
                <>
                  <Button
                    className="flex-1 bg-amber-700 hover:bg-amber-600 text-white h-8 text-xs transition-colors"
                    onClick={handlePause}
                  >
                    <Pause className="w-3.5 h-3.5 mr-1" /> Pause
                  </Button>
                  <Button
                    className="flex-1 bg-red-700 hover:bg-red-600 text-white h-8 text-xs transition-colors"
                    onClick={handleAbort}
                  >
                    <Square className="w-3.5 h-3.5 mr-1" /> Abort
                  </Button>
                </>
              )}

              {isPaused && (
                <>
                  <Button
                    className="flex-1 bg-emerald-700 hover:bg-emerald-600 text-white h-8 text-xs transition-colors"
                    onClick={handleResume}
                  >
                    <RotateCw className="w-3.5 h-3.5 mr-1" /> Resume
                  </Button>
                  <Button
                    className="flex-1 bg-red-700 hover:bg-red-600 text-white h-8 text-xs transition-colors"
                    onClick={handleAbort}
                  >
                    <Square className="w-3.5 h-3.5 mr-1" /> Abort
                  </Button>
                </>
              )}
            </div>

            {/* Status message */}
            {statusMsg && (
              <p className={`text-xs rounded p-2 ${
                statusMsg.toLowerCase().includes('fail') || statusMsg.toLowerCase().includes('error')
                  ? 'text-red-400 bg-red-900/20 border border-red-700/30'
                  : 'text-emerald-400 bg-emerald-900/20 border border-emerald-700/30'
              }`}
              >
                {statusMsg}
              </p>
            )}

            {/* Workflow info */}
            <div className="flex items-center gap-3 text-[10px] text-slate-500"
            >
              <span className="truncate">{definition.workflow!.name}</span>
              <span>·</span>
              <span>{definition.workflow!.tasks.length} tasks</span>
              <span>·</span>
              <span>{definition.workflow!.edges.length} edges</span>
            </div>

          </>
        )}

        {/* Execution History Toggle */}
        <button
          className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 transition-colors mt-1"
          onClick={() => setShowHistory(!showHistory)}
        >
          {showHistory ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          Execution History {history.length > 0 && `(${history.length})`}
        </button>

        {/* Execution History Panel */}
        {showHistory && (
          <div className="space-y-1.5"
          >
            {historyLoading && (
              <div className="text-xs text-slate-500 text-center py-2"
              >
                <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1" />
                Loading...
              </div>
            )}
            {!historyLoading && history.length === 0 && (
              <div className="text-xs text-slate-500 text-center py-2"
              >No execution history yet</div>
            )}
            {history.map(run => (
              <div
                key={run.run_id}
                className="flex items-center justify-between p-2 rounded bg-slate-900/40 border border-slate-700/40 text-xs"
              >
                <div className="min-w-0 flex-1"
                >
                  <div className="flex items-center gap-1.5"
                  >
                    {run.success ? (
                      <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                    ) : (
                      <XCircle className="w-3 h-3 text-red-400 shrink-0" />
                    )}
                    <span className="text-slate-300 truncate">{run.workflow_name}</span>
                    <span className="text-[10px] text-slate-500 shrink-0"
                    >
                      {new Date(run.started_at * 1000).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5"
                  >
                    {run.completed_count}/{run.task_count} tasks · {formatElapsed(run.total_elapsed)}
                  </div>
                </div>
                <a
                  href={`/api/artifact?path=${encodeURIComponent(run.report_path.replace(/^outputs\//, ''))}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cyan-400 hover:text-cyan-300 shrink-0 p-1"
                  title="View report"
                >
                  <FileText className="w-3.5 h-3.5" />
                </a>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
