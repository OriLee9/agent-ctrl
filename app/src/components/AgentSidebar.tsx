import { useState } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import type { AgentSummary, TaskExecutionState } from '@/types';
import {
  Bot,
  MessageSquare,
  Footprints,
  HardDrive,
  ChevronRight,
  ChevronDown,
  Circle,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
} from 'lucide-react';

interface Props {
  agents: AgentSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  taskStates?: Record<string, TaskExecutionState>;
}

interface ParsedAgent {
  agentId: string;
  isTaskConv: boolean;
  baseAgent: string;
  taskName?: string;
}

function parseAgentId(agentId: string): ParsedAgent {
  const parts = agentId.split('/');
  if (parts.length >= 2) {
    return {
      agentId,
      isTaskConv: true,
      baseAgent: parts[0],
      taskName: parts.slice(1).join('/'),
    };
  }
  return { agentId, isTaskConv: false, baseAgent: agentId };
}

function getTaskStateColor(state?: string): string {
  switch (state?.toLowerCase()) {
    case 'running':
      return 'text-emerald-400';
    case 'completed':
      return 'text-blue-400';
    case 'failed':
      return 'text-red-400';
    case 'pending':
      return 'text-amber-400';
    case 'waiting_approval':
      return 'text-purple-400';
    default:
      return 'text-slate-500';
  }
}

function getTaskStateIcon(state?: string) {
  switch (state?.toLowerCase()) {
    case 'running':
      return <Loader2 className="w-3 h-3 animate-spin text-emerald-400" />;
    case 'completed':
      return <CheckCircle2 className="w-3 h-3 text-blue-400" />;
    case 'failed':
      return <XCircle className="w-3 h-3 text-red-400" />;
    case 'pending':
      return <Clock className="w-3 h-3 text-amber-400" />;
    case 'waiting_approval':
      return <Circle className="w-3 h-3 text-purple-400" />;
    default:
      return <Circle className="w-3 h-3 text-slate-600" />;
  }
}

function getTaskStateLabel(state?: string): string {
  switch (state?.toLowerCase()) {
    case 'running':
      return 'running';
    case 'completed':
      return 'done';
    case 'failed':
      return 'failed';
    case 'pending':
      return 'pending';
    case 'waiting_approval':
      return 'approval';
    default:
      return 'idle';
  }
}

interface AgentGroup {
  baseAgent: string;
  base: AgentSummary | null;
  tasks: AgentSummary[];
}

function buildGroups(agents: AgentSummary[]): AgentGroup[] {
  const groups = new Map<string, AgentGroup>();

  for (const agent of agents) {
    const parsed = parseAgentId(agent.agent_id);
    if (!groups.has(parsed.baseAgent)) {
      groups.set(parsed.baseAgent, {
        baseAgent: parsed.baseAgent,
        base: null,
        tasks: [],
      });
    }
    const group = groups.get(parsed.baseAgent)!;
    if (parsed.isTaskConv) {
      group.tasks.push(agent);
    } else {
      group.base = agent;
    }
  }

  return Array.from(groups.values()).sort((a, b) => {
    const aActive = a.tasks.some(t => (t.message_count || 0) > 0);
    const bActive = b.tasks.some(t => (t.message_count || 0) > 0);
    if (aActive !== bActive) return aActive ? -1 : 1;
    return a.baseAgent.localeCompare(b.baseAgent);
  });
}

export default function AgentSidebar({ agents, selectedId, onSelect, taskStates }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (agents.length === 0) {
    return (
      <div className="w-64 bg-slate-800 border-r border-slate-700 flex items-center justify-center text-slate-500">
        <p className="text-sm">No agents registered</p>
      </div>
    );
  }

  const groups = buildGroups(agents);
  const totalTasks = groups.reduce((sum, g) => sum + g.tasks.length, 0);

  const toggleExpand = (baseAgent: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(baseAgent)) {
        next.delete(baseAgent);
      } else {
        next.add(baseAgent);
      }
      return next;
    });
  };

  return (
    <ScrollArea className="w-64 bg-slate-800 border-r border-slate-700/80 h-full">
      <div className="p-3 space-y-0.5">
        {/* Header */}
        <div className="flex items-center justify-between px-2 mb-2">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Agents
          </h2>
          <span className="text-[10px] text-slate-500">
            {groups.length} base{totalTasks > 0 && ` · ${totalTasks} task`}
          </span>
        </div>

        {groups.map(group => {
          const base = group.base;
          const hasTasks = group.tasks.length > 0;
          const isExpanded = expanded.has(group.baseAgent) || hasTasks;
          const anyActive = group.tasks.some(
            t => (t.message_count || 0) > 0 || (t.step_count || 0) > 0
          );
          const runningTask = group.tasks.find(t => {
            const parsed = parseAgentId(t.agent_id);
            const ts = parsed.taskName ? taskStates?.[parsed.taskName] : undefined;
            return ts?.state === 'running';
          });

          return (
            <div key={group.baseAgent} className="mb-1">
              {/* Base Agent Row */}
              <button
                onClick={() => {
                  if (hasTasks) {
                    toggleExpand(group.baseAgent);
                  } else if (base) {
                    onSelect(base.agent_id);
                  }
                }}
                className={cn(
                  'w-full text-left px-2.5 py-2 rounded-md transition-all duration-150 flex items-center gap-2',
                  'hover:bg-slate-700/60',
                  !hasTasks && selectedId === base?.agent_id
                    ? 'bg-slate-700/70 ring-1 ring-cyan-500/40'
                    : 'bg-transparent'
                )}
              >
                {hasTasks ? (
                  isExpanded ? (
                    <ChevronDown className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                  )
                ) : (
                  <span className="w-3.5" />
                )}

                <Bot
                  className={cn(
                    'w-4 h-4 shrink-0',
                    runningTask ? 'text-emerald-400' : anyActive ? 'text-cyan-400' : 'text-slate-500'
                  )}
                />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium text-slate-200 truncate">
                      {group.baseAgent}
                    </span>
                    {runningTask && (
                      <span className="relative flex h-2 w-2 shrink-0">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-0.5">
                    {base && (
                      <>
                        <span className="flex items-center gap-0.5">
                          <MessageSquare className="w-2.5 h-2.5" />
                          {base.message_count}
                        </span>
                        <span className="flex items-center gap-0.5">
                          <Footprints className="w-2.5 h-2.5" />
                          {base.step_count}
                        </span>
                      </>
                    )}
                    {hasTasks && (
                      <span>
                        {group.tasks.length} task{group.tasks.length > 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                </div>
              </button>

              {/* Task Conversations */}
              {hasTasks && isExpanded && (
                <div className="ml-4 pl-3 border-l border-slate-700/50 space-y-0.5 mt-0.5">
                  {group.tasks.map(task => {
                    const parsed = parseAgentId(task.agent_id);
                    const ts = parsed.taskName ? taskStates?.[parsed.taskName] : undefined;
                    const state = ts?.state;

                    return (
                      <button
                        key={task.agent_id}
                        onClick={() => onSelect(task.agent_id)}
                        className={cn(
                          'w-full text-left px-2.5 py-1.5 rounded-md transition-all duration-150 flex items-center gap-2',
                          'hover:bg-slate-700/60',
                          selectedId === task.agent_id
                            ? 'bg-slate-700 ring-1 ring-cyan-500/40'
                            : 'bg-transparent'
                        )}
                      >
                        {getTaskStateIcon(state)}

                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs text-slate-300 truncate">
                              {parsed.taskName}
                            </span>
                            <span
                              className={cn(
                                'text-[9px] px-1 py-0 rounded-full font-medium shrink-0',
                                state?.toLowerCase() === 'running'
                                  ? 'bg-emerald-900/40 text-emerald-400'
                                  : state?.toLowerCase() === 'completed'
                                    ? 'bg-blue-900/40 text-blue-400'
                                    : state?.toLowerCase() === 'failed'
                                      ? 'bg-red-900/40 text-red-400'
                                      : 'bg-slate-800 text-slate-500'
                              )}
                            >
                              {getTaskStateLabel(state)}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-0.5">
                            <span className="flex items-center gap-0.5">
                              <MessageSquare className="w-2.5 h-2.5" />
                              {task.message_count}
                            </span>
                            <span className="flex items-center gap-0.5">
                              <Footprints className="w-2.5 h-2.5" />
                              {task.step_count}
                            </span>
                            {ts && ts.elapsed > 0 && (
                              <span>{ts.elapsed.toFixed(1)}s</span>
                            )}
                            {ts && ts.error && (
                              <span className="text-red-400 truncate max-w-[80px]">{ts.error}</span>
                            )}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}
