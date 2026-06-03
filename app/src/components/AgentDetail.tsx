import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { AgentDetail as AgentDetailType } from '@/types';
import MessageFlow from './MessageFlow';
import StepChain from './StepChain';
import { MessageSquare, Footprints, Cpu, PauseCircle, PlayCircle } from 'lucide-react';

interface Props {
  detail: AgentDetailType;
}

export default function AgentDetail({ detail }: Props) {
  const summary = detail.summary;
  const isPaused = summary.metadata?.paused as boolean || false;
  const isAborted = summary.metadata?.aborted as boolean || false;

  let statusBadge = (
    <Badge variant="outline" className="bg-emerald-900/30 text-emerald-400 border-emerald-700 text-xs gap-1">
      <PlayCircle className="w-3 h-3" /> Active
    </Badge>
  );
  if (isAborted) {
    statusBadge = (
      <Badge variant="outline" className="bg-red-900/30 text-red-400 border-red-700 text-xs">
        Aborted
      </Badge>
    );
  } else if (isPaused) {
    statusBadge = (
      <Badge variant="outline" className="bg-amber-900/30 text-amber-400 border-amber-700 text-xs gap-1">
        <PauseCircle className="w-3 h-3" /> Paused
      </Badge>
    );
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="px-5 py-3 border-b border-slate-700/80 bg-slate-800/50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <h2 className="text-base font-bold text-white truncate">{detail.agent_id}</h2>
            {statusBadge}
          </div>
        </div>

        {/* Stats */}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 mt-2">
          <div className="flex items-center gap-1.5 text-sm text-slate-400">
            <MessageSquare className="w-4 h-4 text-blue-400 shrink-0" />
            <span>{summary.message_count} messages</span>
          </div>
          <div className="flex items-center gap-1.5 text-sm text-slate-400">
            <Footprints className="w-4 h-4 text-amber-400 shrink-0" />
            <span>{summary.step_count} steps</span>
          </div>
          <div className="flex items-center gap-1.5 text-sm text-slate-400">
            <Cpu className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{summary.total_usage.total_tokens} tokens</span>
          </div>
          <span className="hidden sm:inline text-xs text-slate-500 ml-auto">
            prompt: {summary.total_usage.prompt_tokens} / completion: {summary.total_usage.completion_tokens}
          </span>
        </div>
        {/* Mobile token detail */}
        <div className="sm:hidden text-[10px] text-slate-500 mt-1">
          prompt: {summary.total_usage.prompt_tokens} / completion: {summary.total_usage.completion_tokens}
        </div>
      </div>

      {/* Content Tabs */}
      <Tabs defaultValue="messages" className="flex-1 flex flex-col min-h-0">
        <TabsList className="mx-5 mt-3 bg-slate-800/80 border border-slate-700/60 w-fit">
          <TabsTrigger value="messages" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-cyan-300 transition-colors">
            Messages
          </TabsTrigger>
          <TabsTrigger value="steps" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-cyan-300 transition-colors">
            Steps ({summary.step_count})
          </TabsTrigger>
          <TabsTrigger value="snapshots" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-cyan-300 transition-colors">
            Snapshots ({detail.snapshots.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="messages" className="flex-1 min-h-[120px] mt-2 flex flex-col overflow-hidden">
          <div className="flex-1 min-h-0 overflow-hidden">
            <MessageFlow messages={detail.messages} />
          </div>
        </TabsContent>

        <TabsContent value="steps" className="flex-1 min-h-[120px] mt-2 flex flex-col overflow-hidden">
          <div className="flex-1 min-h-0 overflow-hidden">
            <StepChain steps={detail.steps} />
          </div>
        </TabsContent>

        <TabsContent value="snapshots" className="flex-1 min-h-0 mt-2 p-3 overflow-auto flex flex-col">
          {detail.snapshots.length === 0 ? (
            <p className="text-slate-500 text-sm text-center py-8">No snapshots</p>
          ) : (
            <div className="space-y-2">
              {detail.snapshots.map(snap => (
                <Card key={snap.snapshot_id} className="bg-slate-800/60 border-slate-700/60 card-hover">
                  <CardContent className="py-2.5 px-3 flex items-center justify-between text-xs">
                    <span className="text-slate-300 font-mono text-[11px] truncate">{snap.snapshot_id}</span>
                    <div className="flex gap-3 text-slate-500 shrink-0">
                      <span>{snap.message_count} msgs</span>
                      <span>{snap.step_count} steps</span>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
