import { useState, useMemo } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { WorkflowEvent } from '@/types';
import {
  Activity,
  Wifi,
  WifiOff,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  Package,
  AlertTriangle,
  Filter,
  Trash2,
} from 'lucide-react';

interface Props {
  events: WorkflowEvent[];
  connected: boolean;
  onSelectAgent?: (agentId: string) => void;
}

function getEventColor(type: string): string {
  const colors: Record<string, string> = {
    agent_registered: 'text-emerald-400',
    agent_unregistered: 'text-red-400',
    message_added: 'text-blue-400',
    system_updated: 'text-purple-400',
    step_recorded: 'text-amber-400',
    snapshot_created: 'text-cyan-400',
    rollback: 'text-orange-400',
    intervention: 'text-rose-400',
    agent_to_agent: 'text-teal-400',
    workflow_state_change: 'text-indigo-400',
    workflow_complete: 'text-emerald-400',
    workflow_error: 'text-red-400',
    task_started: 'text-cyan-400',
    task_completed: 'text-violet-400',
  };
  return colors[type] || 'text-slate-400';
}

function getEventIcon(type: string): React.ReactNode {
  if (type === 'task_completed') return <CheckCircle2 className="w-3 h-3" />;
  if (type === 'task_started') return <Loader2 className="w-3 h-3 animate-spin" />;
  if (type === 'workflow_error') return <XCircle className="w-3 h-3" />;
  if (type === 'workflow_state_change') return <Clock className="w-3 h-3" />;
  return null;
}

function formatTime(ts: number): string {
  try {
    return new Date(ts * 1000).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return '';
  }
}

function EventDetail({ data }: { data: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const entries = Object.entries(data).filter(([k]) => k !== 'timestamp' && k !== '_id');
  if (entries.length === 0) return null;

  const simpleEntries = entries.filter(([, v]) => typeof v !== 'object' || v === null);
  const complexEntries = entries.filter(([, v]) => typeof v === 'object' && v !== null);

  return (
    <div className="mt-1">
      {simpleEntries.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5">
          {simpleEntries.map(([k, v]) => (
            <span key={k} className="text-[10px] text-slate-500">
              <span className="text-slate-600">{k}:</span>{' '}
              <span className="text-slate-400 font-mono">
                {typeof v === 'string' ? v : JSON.stringify(v)}
              </span>
            </span>
          ))}
        </div>
      )}
      {complexEntries.length > 0 && (
        <>
          <Button
            variant="ghost"
            size="sm"
            className="h-4 px-0 text-[10px] text-slate-600 hover:text-slate-400"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? <ChevronUp className="w-3 h-3 mr-0.5" /> : <ChevronDown className="w-3 h-3 mr-0.5" />}
            details
          </Button>
          {expanded && (
            <div className="mt-1 p-1.5 rounded bg-slate-800/60 text-[10px] font-mono text-slate-400 whitespace-pre-wrap break-words max-h-40 overflow-auto">
              {JSON.stringify(Object.fromEntries(complexEntries), null, 2)}
            </div>
          )}
        </>
      )}
    </div>
  );
}

const ALL_TYPES = 'all';

export default function EventLog({ events, connected, onSelectAgent }: Props) {
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set());
  const [filterType, setFilterType] = useState<string>(ALL_TYPES);

  const eventTypes = useMemo(() => {
    const types = new Set<string>();
    events.forEach(e => { if (e.type) types.add(e.type); });
    return Array.from(types).sort();
  }, [events]);

  const filteredEvents = useMemo(() => {
    if (filterType === ALL_TYPES) return events;
    return events.filter(e => e.type === filterType);
  }, [events, filterType]);

  const toggleExpand = (id: string) => {
    setExpandedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const clearFilter = () => setFilterType(ALL_TYPES);

  return (
    <div className="h-full flex flex-col bg-slate-800/50 border-t border-slate-700/80">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700/50">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-slate-400" />
          <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
            Event Stream
          </span>
          <Badge variant="outline" className="text-xs px-1.5 py-0 bg-slate-800 text-slate-400 border-slate-700 font-mono">
            {filteredEvents.length}
            {filterType !== ALL_TYPES && ` / ${events.length}`}
          </Badge>
          {events.length >= 200 && (
            <span className="text-[10px] text-slate-600">(last 200)</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Type filter */}
          <div className="flex items-center gap-1">
            <Filter className="w-3 h-3 text-slate-500" />
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="text-[10px] bg-slate-800 text-slate-400 border border-slate-700 rounded px-1.5 py-0.5 focus:outline-none focus:border-slate-500"
            >
              <option value={ALL_TYPES}>All types</option>
              {eventTypes.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            {filterType !== ALL_TYPES && (
              <button
                onClick={clearFilter}
                className="text-[10px] text-slate-500 hover:text-slate-300"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            )}
          </div>
          {/* Connection status */}
          <div className="flex items-center gap-1.5">
            {connected ? (
              <Wifi className="w-3 h-3 text-emerald-400" />
            ) : (
              <WifiOff className="w-3 h-3 text-red-400" />
            )}
            <span className={cn('text-xs', connected ? 'text-emerald-400' : 'text-red-400')}>
              {connected ? 'Live' : 'Disconnected'}
            </span>
          </div>
        </div>
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="p-2 space-y-0.5">
          {filteredEvents.length === 0 && (
            <p className="text-slate-500 text-xs text-center py-4">
              {filterType !== ALL_TYPES ? `No ${filterType} events found` : 'Waiting for events...'}
            </p>
          )}
          {filteredEvents.map((evt) => {
            const id = (evt as unknown as Record<string, string>)._id || `${evt.type}_${evt.timestamp}`;
            const isExpanded = expandedEvents.has(id);
            const hasDetails = evt.data && Object.keys(evt.data).length > 1;
            const ts = typeof evt.timestamp === 'number' ? evt.timestamp : 0;
            return (
              <div
                key={id}
                className="px-2 py-1 rounded text-xs hover:bg-slate-700/30 transition-colors cursor-pointer"
                onClick={() => hasDetails && toggleExpand(id)}
              >
                <div className="flex items-start gap-2">
                  {/* Timestamp */}
                  {ts > 0 && (
                    <span className="text-[10px] text-slate-600 font-mono shrink-0 mt-0.5 w-[50px] text-right">
                      {formatTime(ts)}
                    </span>
                  )}
                  <span className={cn('font-mono shrink-0 mt-0.5 flex items-center gap-1', getEventColor(evt.type))}>
                    {getEventIcon(evt.type)}
                    {evt.type}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      {evt.data?.agent_id && onSelectAgent ? (
                        <button
                          className="text-slate-500 truncate max-w-[160px] hover:text-cyan-400 hover:underline text-left"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectAgent(evt.data.agent_id as string);
                          }}
                        >
                          {evt.data.agent_id as string}
                        </button>
                      ) : (
                        <span className="text-slate-500 truncate">
                          {(evt.data?.agent_id as string) || (evt.data?.task_name as string) || ''}
                        </span>
                      )}
                      {typeof evt.data?.state === 'string' && (
                        <Badge variant="outline" className="text-[10px] px-1 py-0 h-4 bg-slate-800 text-slate-400 border-slate-700 shrink-0">
                          {evt.data.state as string}
                        </Badge>
                      )}
                      {Array.isArray(evt.data?.artifacts) && (evt.data.artifacts as unknown[]).length > 0 && (
                        <span className="flex items-center gap-0.5 text-[10px] text-cyan-400 shrink-0">
                          <Package className="w-3 h-3" />
                          {(evt.data.artifacts as unknown[]).length}
                        </span>
                      )}
                      {typeof evt.data?.error === 'string' && (
                        <span className="flex items-center gap-0.5 text-[10px] text-red-400 shrink-0">
                          <AlertTriangle className="w-3 h-3" />
                        </span>
                      )}
                      {hasDetails && (
                        <span className="text-slate-600 ml-auto shrink-0">
                          {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                        </span>
                      )}
                    </div>
                    {isExpanded && <EventDetail data={evt.data} />}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}
