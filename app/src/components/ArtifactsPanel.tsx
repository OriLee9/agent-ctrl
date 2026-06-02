import { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { WorkflowExecutionDetail, TaskExecutionState } from '@/types';
import { Package, FileText, Image, FileCode, FolderOpen, ExternalLink } from 'lucide-react';

interface Props {
  execution: WorkflowExecutionDetail | null;
  taskStates: Record<string, TaskExecutionState>;
}

function getFileIcon(path: string): React.ReactNode {
  const lower = path.toLowerCase();
  if (lower.endsWith('.png') || lower.endsWith('.jpg') || lower.endsWith('.jpeg') || lower.endsWith('.gif') || lower.endsWith('.svg')) {
    return <Image className="w-3.5 h-3.5 text-purple-400" />;
  }
  if (lower.endsWith('.py') || lower.endsWith('.js') || lower.endsWith('.ts') || lower.endsWith('.json') || lower.endsWith('.yaml') || lower.endsWith('.yml')) {
    return <FileCode className="w-3.5 h-3.5 text-cyan-400" />;
  }
  if (lower.endsWith('.md') || lower.endsWith('.txt') || lower.endsWith('.log')) {
    return <FileText className="w-3.5 h-3.5 text-amber-400" />;
  }
  return <FolderOpen className="w-3.5 h-3.5 text-slate-400" />;
}

function extractFilename(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export default function ArtifactsPanel({ execution, taskStates }: Props) {
  const artifacts = useMemo(() => {
    const list: Array<{
      path: string;
      name: string;
      taskName: string;
      state: string;
      agentId: string;
    }> = [];
    if (!execution) return list;

    // Collect from task_executions (includes historical runs)
    for (const [taskName, exec] of Object.entries(execution.task_executions)) {
      for (const art of exec.artifacts || []) {
        list.push({
          path: art,
          name: extractFilename(art),
          taskName,
          state: exec.state,
          agentId: exec.agent_id,
        });
      }
    }

    // Also collect from live taskStates if not already present
    for (const [taskName, state] of Object.entries(taskStates)) {
      for (const art of state.artifacts || []) {
        if (!list.some((a) => a.path === art && a.taskName === taskName)) {
          list.push({
            path: art,
            name: extractFilename(art),
            taskName,
            state: state.state,
            agentId: state.agent_id,
          });
        }
      }
    }

    return list;
  }, [execution, taskStates]);

  if (artifacts.length === 0) {
    return (
      <Card className="bg-slate-800/40 border-slate-700/60">
        <CardHeader className="py-2.5 px-4">
          <CardTitle className="text-xs flex items-center gap-2 text-slate-300">
            <Package className="w-4 h-4 text-slate-400" />
            Artifacts
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <p className="text-xs text-slate-500 text-center py-4">No artifacts produced yet</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-slate-800/40 border-slate-700/60">
      <CardHeader className="py-2.5 px-4">
        <CardTitle className="text-xs flex items-center gap-2 text-slate-300">
          <Package className="w-4 h-4 text-slate-400" />
          Artifacts
          <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-slate-700/50 text-slate-400 border-slate-600">
            {artifacts.length}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <ScrollArea className="max-h-[200px]">
          <div className="space-y-1.5">
            {artifacts.map((art, i) => (
              <div
                key={i}
                className="flex items-center gap-2 p-2 rounded-md bg-slate-900/40 border border-slate-700/30 hover:border-slate-600/50 transition-colors"
              >
                {getFileIcon(art.path)}
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-slate-300 truncate font-mono">{art.name}</div>
                  <div className="text-[10px] text-slate-500 truncate">{art.taskName} · {art.agentId || '—'}</div>
                </div>
                <a
                  href={`/api/artifact?path=${encodeURIComponent(art.path)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-slate-500 hover:text-cyan-400 transition-colors"
                  title="Open artifact"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
