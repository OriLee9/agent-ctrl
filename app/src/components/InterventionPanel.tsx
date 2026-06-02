import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { intervene } from '@/hooks/useApi';
import { Pause, Play, Square, Send, AlertTriangle } from 'lucide-react';

interface Props {
  agentId: string | null;
}

export default function InterventionPanel({ agentId }: Props) {
  const [insertContent, setInsertContent] = useState('');
  const [sending, setSending] = useState(false);

  if (!agentId) {
    return (
      <div className="h-full flex items-center justify-center text-slate-500 text-sm px-4 text-center">
        Select an agent to intervene
      </div>
    );
  }

  const handleAction = async (type: string, data?: Record<string, unknown>) => {
    setSending(true);
    await intervene(type, agentId, data);
    setSending(false);
  };

  const handleInsert = async () => {
    if (!insertContent.trim()) return;
    await handleAction('insert', {
      role: 'system',
      content: insertContent,
    });
    setInsertContent('');
  };

  return (
    <div className="h-full flex flex-col bg-slate-800/50 border-l border-slate-700/80">
      <div className="px-4 py-2 border-b border-slate-700/50">
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider truncate block">
          Intervene: {agentId}
        </span>
      </div>

      <div className="flex-1 overflow-auto p-4 space-y-4">
        {/* Quick Actions */}
        <div className="space-y-2">
          <Label className="text-xs text-slate-400">Quick Actions</Label>
          <div className="flex flex-col gap-1.5">
            <Button
              size="sm"
              variant="outline"
              className="border-amber-700/60 text-amber-400 hover:bg-amber-900/25 h-8 text-xs justify-start"
              onClick={() => handleAction('pause')}
              disabled={sending}
            >
              <Pause className="w-3.5 h-3.5 mr-1.5" /> Pause Agent
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="border-emerald-700/60 text-emerald-400 hover:bg-emerald-900/25 h-8 text-xs justify-start"
              onClick={() => handleAction('resume')}
              disabled={sending}
            >
              <Play className="w-3.5 h-3.5 mr-1.5" /> Resume Agent
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="border-red-700/60 text-red-400 hover:bg-red-900/25 h-8 text-xs justify-start"
              onClick={() => handleAction('abort')}
              disabled={sending}
            >
              <Square className="w-3.5 h-3.5 mr-1.5" /> Abort Agent
            </Button>
          </div>
        </div>

        {/* Insert Message */}
        <div className="space-y-2">
          <Label className="text-xs text-slate-400 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            Insert System Message
          </Label>
          <Textarea
            value={insertContent}
            onChange={(e) => setInsertContent(e.target.value)}
            placeholder="Type a message to insert into the agent's context..."
            className="bg-slate-900 border-slate-600 text-slate-200 text-xs resize-none h-20 placeholder:text-slate-600"
          />
          <Button
            size="sm"
            className="w-full bg-cyan-700 hover:bg-cyan-600 text-white h-8 text-xs transition-colors"
            onClick={handleInsert}
            disabled={!insertContent.trim() || sending}
          >
            <Send className="w-3.5 h-3.5 mr-1" /> Send
          </Button>
        </div>
      </div>
    </div>
  );
}
