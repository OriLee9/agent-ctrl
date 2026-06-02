import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { agentRegister, useAgentTemplates } from '@/hooks/useApi';
import { Bot, Plus, Key, Cpu, Loader2 } from 'lucide-react';

interface Props {
  onRegister: (agentId: string) => void;
  registeredAgents: string[];
}

export default function AgentConfig({ onRegister, registeredAgents }: Props) {
  const templates = useAgentTemplates();
  const [agentId, setAgentId] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('deepseek-chat');
  const [temperature, setTemperature] = useState(0.7);
  const [maxIterations, setMaxIterations] = useState(15);
  const [systemPrompt, setSystemPrompt] = useState('');
  const [registering, setRegistering] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const handleRegister = async () => {
    if (!agentId.trim()) {
      setError('Agent ID is required');
      return;
    }
    setRegistering(true);
    setError('');
    setSuccess('');
    try {
      const res = await agentRegister({
        agent_id: agentId.trim(),
        api_key: apiKey || undefined,
        model,
        temperature,
        max_iterations: maxIterations,
        system_prompt: systemPrompt || undefined,
      });
      if (res.error) {
        setError(String(res.error));
      } else {
        setSuccess(`Agent "${res.agent_id}" registered`);
        onRegister(agentId.trim());
        setAgentId('');
      }
    } catch {
      setError('Registration failed');
    } finally {
      setRegistering(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/80 bg-slate-800/50">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-purple-400" />
          <h2 className="text-sm font-semibold text-slate-200">Agent Config</h2>
        </div>
        <Badge variant="outline" className="text-xs bg-slate-700/60 text-slate-300 border-slate-600">
          {registeredAgents.length} registered
        </Badge>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-5">
          {/* Registered Agents */}
          {registeredAgents.length > 0 && (
            <div className="space-y-1.5">
              <Label className="text-xs text-slate-400">Registered Agents</Label>
              <div className="flex flex-wrap gap-1.5">
                {registeredAgents.map(a => (
                  <Badge key={a} variant="outline" className="bg-emerald-900/20 text-emerald-400 border-emerald-700/50 text-xs">
                    <Bot className="w-3 h-3 mr-1" /> <span className="truncate max-w-[120px]">{a}</span>
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Register New Agent */}
          <Card className="bg-slate-800/60 border-slate-700/60">
            <CardHeader className="py-2 px-3">
              <CardTitle className="text-xs text-slate-300 flex items-center gap-1">
                <Plus className="w-3.5 h-3.5" /> Register New Agent
              </CardTitle>
            </CardHeader>
            <CardContent className="px-3 pb-3 space-y-3">
              {/* Agent ID */}
              <div className="space-y-1">
                <Label className="text-xs text-slate-400">Agent ID</Label>
                <Input
                  value={agentId}
                  onChange={e => setAgentId(e.target.value)}
                  placeholder="e.g. researcher, coder"
                  className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8"
                />
              </div>

              {/* API Key */}
              <div className="space-y-1">
                <Label className="text-xs text-slate-400 flex items-center gap-1">
                  <Key className="w-3 h-3" /> API Key
                </Label>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={e => setApiKey(e.target.value)}
                  placeholder="Uses .env DEEPSEEK_API_KEY if blank"
                  className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8 placeholder:text-slate-600"
                />
              </div>

              {/* Model */}
              <div className="space-y-1">
                <Label className="text-xs text-slate-400 flex items-center gap-1">
                  <Cpu className="w-3 h-3" /> Model
                </Label>
                <Select value={model} onValueChange={setModel}>
                  <SelectTrigger className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-800 border-slate-700 text-slate-200">
                    {(templates?.llm_providers || []).flatMap(p =>
                      p.models.map(m => (
                        <SelectItem key={`${p.id}:${m}`} value={m}>
                          {p.name} — {m}
                        </SelectItem>
                      ))
                    )}
                    <SelectItem value="deepseek-chat">DeepSeek — deepseek-chat</SelectItem>
                    <SelectItem value="deepseek-reasoner">DeepSeek — deepseek-reasoner</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Temperature */}
              <div className="space-y-1">
                <Label className="text-xs text-slate-400">Temperature: {temperature.toFixed(1)}</Label>
                <Slider
                  value={[temperature]}
                  onValueChange={v => setTemperature(v[0])}
                  min={0}
                  max={2}
                  step={0.1}
                  className="w-full"
                />
              </div>

              {/* Max Iterations */}
              <div className="space-y-1">
                <Label className="text-xs text-slate-400">Max Iterations: {maxIterations}</Label>
                <Slider
                  value={[maxIterations]}
                  onValueChange={v => setMaxIterations(v[0])}
                  min={1}
                  max={50}
                  step={1}
                  className="w-full"
                />
              </div>

              {/* System Prompt */}
              <div className="space-y-1">
                <Label className="text-xs text-slate-400">System Prompt (optional)</Label>
                <Textarea
                  value={systemPrompt}
                  onChange={e => setSystemPrompt(e.target.value)}
                  placeholder="Custom system prompt for this agent..."
                  className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-20 resize-none placeholder:text-slate-600"
                />
              </div>

              {error && (
                <p className="text-xs text-red-400 bg-red-900/20 border border-red-700/30 rounded p-2">{error}</p>
              )}
              {success && (
                <p className="text-xs text-emerald-400 bg-emerald-900/20 border border-emerald-700/30 rounded p-2">{success}</p>
              )}

              <Button
                className="w-full bg-purple-700 hover:bg-purple-600 text-white h-8 text-xs transition-colors"
                onClick={handleRegister}
                disabled={registering || !agentId.trim()}
              >
                {registering ? (
                  <><Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> Registering...</>
                ) : (
                  <><Plus className="w-3.5 h-3.5 mr-1" /> Register Agent</>
                )}
              </Button>
            </CardContent>
          </Card>
        </div>
      </ScrollArea>
    </div>
  );
}
