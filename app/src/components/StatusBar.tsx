import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Camera, PauseCircle, PlayCircle } from 'lucide-react';
import type { SystemStatus } from '@/types';
import { createSnapshot, toggleRuleEngine } from '@/hooks/useApi';

interface Props {
  status: SystemStatus;
  onRefresh: () => void;
}

export default function StatusBar({ status, onRefresh }: Props) {
  const handleSnapshot = async () => {
    await createSnapshot();
    onRefresh();
  };

  const handleToggleRuleEngine = async () => {
    await toggleRuleEngine(!status.rule_engine_running);
    onRefresh();
  };

  return (
    <div className="flex items-center justify-between px-5 py-2.5 bg-slate-900 text-white border-b border-slate-700/80">
      <div className="flex items-center gap-3 min-w-0">
        <h1 className="text-base font-bold tracking-tight text-white shrink-0">Agent Workflow Monitor</h1>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="bg-slate-700/60 text-slate-200 border-0 text-xs font-normal">
            {status.agent_count} Agents
          </Badge>
          <Badge variant="secondary" className="bg-slate-700/60 text-slate-200 border-0 text-xs font-normal">
            {status.snapshot_count} Snapshots
          </Badge>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Button
          size="sm"
          variant="outline"
          className="border-slate-600 text-slate-300 hover:bg-slate-700 hover:text-white h-8 text-xs transition-colors"
          onClick={handleSnapshot}
        >
          <Camera className="w-3.5 h-3.5 mr-1" />
          Snapshot All
        </Button>
        <Button
          size="sm"
          variant={status.rule_engine_running ? "default" : "outline"}
          className={status.rule_engine_running
            ? "bg-amber-600 hover:bg-amber-500 text-white h-8 text-xs transition-colors"
            : "border-slate-600 text-slate-300 hover:bg-slate-700 hover:text-white h-8 text-xs transition-colors"
          }
          onClick={handleToggleRuleEngine}
        >
          {status.rule_engine_running ? (
            <><PauseCircle className="w-3.5 h-3.5 mr-1" /> Rule Engine On</>
          ) : (
            <><PlayCircle className="w-3.5 h-3.5 mr-1" /> Rule Engine Off</>
          )}
        </Button>
      </div>
    </div>
  );
}
