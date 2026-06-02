import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import type { StepRecord } from '@/types';
import {
  Brain,
  Hammer,
  Eye,
  ChevronDown,
  ChevronUp,
  Clock,
  Cpu,
  AlertCircle,
} from 'lucide-react';

interface Props {
  steps: StepRecord[];
}

type StepPhase = 'thought' | 'action' | 'observation';

interface ParsedStep {
  stepId: string;
  iteration: number;
  timestamp: number;
  phases: Array<{
    phase: StepPhase;
    content: string | Record<string, unknown> | null;
    usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null;
    intervention?: Record<string, unknown> | null;
  }>;
}

function parseSteps(steps: StepRecord[]): ParsedStep[] {
  const groups: Record<number, StepRecord[]> = {};
  for (const s of steps) {
    if (!groups[s.iteration]) groups[s.iteration] = [];
    groups[s.iteration].push(s);
  }

  return Object.entries(groups)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([iteration, records]) => {
      const first = records[0];
      const phases: ParsedStep['phases'] = [];

      // Thought
      if (first.thought) {
        phases.push({ phase: 'thought', content: first.thought, usage: first.usage });
      }
      // Action
      if (first.action && Object.keys(first.action).length > 0) {
        phases.push({ phase: 'action', content: first.action, intervention: first.intervention });
      }
      // Observation
      if (first.observation) {
        phases.push({ phase: 'observation', content: first.observation });
      }

      return {
        stepId: first.step_id,
        iteration: Number(iteration),
        timestamp: first.timestamp,
        phases,
      };
    });
}

const phaseConfig: Record<
  StepPhase,
  { icon: React.ReactNode; label: string; badgeClass: string; lineClass: string }
> = {
  thought: {
    icon: <Brain className="w-3.5 h-3.5" />,
    label: 'Thought',
    badgeClass: 'bg-purple-900/40 text-purple-300 border-purple-700',
    lineClass: 'bg-purple-500',
  },
  action: {
    icon: <Hammer className="w-3.5 h-3.5" />,
    label: 'Action',
    badgeClass: 'bg-cyan-900/40 text-cyan-300 border-cyan-700',
    lineClass: 'bg-cyan-500',
  },
  observation: {
    icon: <Eye className="w-3.5 h-3.5" />,
    label: 'Observation',
    badgeClass: 'bg-amber-900/40 text-amber-300 border-amber-700',
    lineClass: 'bg-amber-500',
  },
};

function PhaseCard({
  phase,
  content,
  usage,
  intervention,
  isLast,
}: {
  phase: StepPhase;
  content: string | Record<string, unknown> | null;
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null;
  intervention?: Record<string, unknown> | null;
  isLast: boolean;
}) {
  const [expanded, setExpanded] = useState(true);
  const cfg = phaseConfig[phase];
  const text = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
  const isLong = text.length > 300;
  const displayText = expanded ? text : text.slice(0, 300) + (isLong ? '...' : '');

  return (
    <div className="relative flex gap-3">
      {/* Timeline line */}
      <div className="flex flex-col items-center">
        <div className={`w-2.5 h-2.5 rounded-full ${cfg.lineClass} ring-2 ring-slate-800 shrink-0`} />
        {!isLast && <div className="w-0.5 flex-1 bg-slate-700/60 my-1" />}
      </div>

      {/* Content */}
      <div className="flex-1 pb-4 min-w-0">
        <div className="flex items-center gap-2 mb-1.5">
          <Badge variant="outline" className={`text-[10px] px-1.5 py-0 h-5 gap-1 ${cfg.badgeClass}`}>
            {cfg.icon}
            {cfg.label}
          </Badge>
          {intervention && Object.keys(intervention).length > 0 && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-5 bg-rose-900/30 text-rose-300 border-rose-700 gap-1">
              <AlertCircle className="w-3 h-3" />
              Intervention
            </Badge>
          )}
          {isLong && (
            <Button
              variant="ghost"
              size="sm"
              className="h-5 px-1 text-[10px] text-slate-500 hover:text-slate-300"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </Button>
          )}
        </div>
        <div className="text-xs text-slate-300 font-mono bg-slate-900/50 rounded-md p-2.5 border border-slate-700/50 whitespace-pre-wrap break-words leading-relaxed max-h-64 overflow-y-auto">
          {displayText}
        </div>
        {usage && usage.total_tokens > 0 && (
          <div className="flex items-center gap-1 mt-1 text-[10px] text-slate-500">
            <Cpu className="w-3 h-3" />
            <span>{usage.total_tokens} tokens</span>
            <span className="text-slate-600">·</span>
            <span>prompt {usage.prompt_tokens}</span>
            <span className="text-slate-600">·</span>
            <span>completion {usage.completion_tokens}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function StepChain({ steps }: Props) {
  const parsed = parseSteps(steps);

  if (parsed.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        No steps recorded
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        {parsed.map((step) => (
          <Card key={step.stepId} className="bg-slate-800/40 border-slate-700/60">
            <CardHeader className="py-2.5 px-4 pb-2">
              <CardTitle className="text-xs flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <Badge
                    variant="outline"
                    className="bg-slate-700/50 text-slate-300 border-slate-600 text-[10px] shrink-0"
                  >
                    Iteration #{step.iteration}
                  </Badge>
                  <span className="text-slate-500 font-mono text-[10px] truncate">{step.stepId}</span>
                </div>
                <div className="flex items-center gap-1 text-[10px] text-slate-500 shrink-0 ml-2">
                  <Clock className="w-3 h-3" />
                  {new Date(step.timestamp * 1000).toLocaleTimeString()}
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 py-0 pb-4">
              {step.phases.map((p, idx) => (
                <PhaseCard
                  key={idx}
                  phase={p.phase}
                  content={p.content}
                  usage={p.usage ?? undefined}
                  intervention={p.intervention ?? undefined}
                  isLast={idx === step.phases.length - 1}
                />
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
    </ScrollArea>
  );
}
