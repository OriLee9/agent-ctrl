import { useState, useCallback, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  workflowDefine,
  useWorkflowDefinition,
  type TaskDef,
  type EdgeDef,
} from '@/hooks/useApi';
import WorkflowDAG from './WorkflowDAG';
import { Plus, Trash2, ArrowRight, Save, GitBranch } from 'lucide-react';

interface Props {
  registeredAgents: string[];
}

export default function WorkflowBuilder({ registeredAgents }: Props) {
  const { definition, refetch } = useWorkflowDefinition();
  const [wfName, setWfName] = useState('my_workflow');
  const [wfMode, setWfMode] = useState<'free' | 'fixed'>('free');
  const [tasks, setTasks] = useState<TaskDef[]>([]);
  const [edges, setEdges] = useState<EdgeDef[]>([]);
  const [newTask, setNewTask] = useState<TaskDef>({
    name: '',
    description: '',
    agent_id: '',
  });
  const [edgeFrom, setEdgeFrom] = useState('');
  const [edgeTo, setEdgeTo] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // 同步已定义的 workflow 到本地状态
  useEffect(() => {
    if (definition?.defined && definition.workflow) {
      const wf = definition.workflow;
      if (wf.name) setWfName(wf.name);
      if (wf.tasks && wf.tasks.length > 0) {
        setTasks(wf.tasks.map((t: Record<string, unknown>) => ({
          name: String(t.name || ''),
          description: String(t.description || ''),
          agent_id: String(t.agent_id || ''),
          expected_output: t.expected_output ? String(t.expected_output) : undefined,
          requires_approval: t.requires_approval as boolean | undefined,
          max_retries: t.max_retries as number | undefined,
          temperature: t.temperature as number | undefined,
        })));
      }
      if (wf.edges && wf.edges.length > 0) {
        setEdges(wf.edges.map((e: { from?: string; to?: string }) => ({
          from: e.from || '',
          to: e.to || '',
        })));
      }
    }
  }, [definition?.defined, definition?.workflow?.workflow_id]);

  const addTask = useCallback(() => {
    if (!newTask.name.trim() || !newTask.description.trim()) return;
    setTasks(prev => [...prev, { ...newTask }]);
    setNewTask({ name: '', description: '', agent_id: '' });
  }, [newTask]);

  const removeTask = useCallback((name: string) => {
    setTasks(prev => prev.filter(t => t.name !== name));
    setEdges(prev => prev.filter(e => e.from !== name && e.to !== name));
  }, []);

  const addEdge = useCallback(() => {
    if (!edgeFrom || !edgeTo || edgeFrom === edgeTo) return;
    if (edges.find(e => e.from === edgeFrom && e.to === edgeTo)) return;
    setEdges(prev => [...prev, { from: edgeFrom, to: edgeTo }]);
    setEdgeFrom('');
    setEdgeTo('');
  }, [edgeFrom, edgeTo, edges]);

  const removeEdge = useCallback((idx: number) => {
    setEdges(prev => prev.filter((_, i) => i !== idx));
  }, []);

  const handleSave = useCallback(async () => {
    if (tasks.length === 0) {
      setError('At least one task required');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const res = await workflowDefine(wfName, tasks, edges, wfMode);
      if (res.error) {
        setError(String(res.error));
      } else {
        refetch();
      }
    } catch {
      setError('Save failed');
    } finally {
      setSaving(false);
    }
  }, [wfName, tasks, edges, refetch]);

  const hasDefinition = definition?.defined && definition?.workflow;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/80 bg-slate-800/50">
        <div className="flex items-center gap-2 min-w-0">
          <GitBranch className="w-4 h-4 text-cyan-400 shrink-0" />
          <h2 className="text-sm font-semibold text-slate-200 truncate">Workflow Builder</h2>
          {hasDefinition && (
            <Badge variant="outline" className="text-xs bg-emerald-900/30 text-emerald-400 border-emerald-700/60 shrink-0">
              Defined: {definition.workflow!.name}
            </Badge>
          )}
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-5">
          {/* Workflow Name + Mode */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-slate-400">Workflow Name</Label>
              <div className="flex items-center gap-1 text-[10px]">
                <button
                  onClick={() => setWfMode('free')}
                  className={`px-2 py-0.5 rounded transition-colors ${wfMode === 'free' ? 'bg-cyan-700 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'}`}
                >
                  Free
                </button>
                <button
                  onClick={() => setWfMode('fixed')}
                  className={`px-2 py-0.5 rounded transition-colors ${wfMode === 'fixed' ? 'bg-amber-700 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'}`}
                >
                  Fixed
                </button>
              </div>
            </div>
            <Input
              value={wfName}
              onChange={e => setWfName(e.target.value)}
              className="bg-slate-900 border-slate-700 text-slate-200 text-sm h-9"
              placeholder="my_workflow"
            />
          </div>

          {/* Add Task */}
          <Card className="bg-slate-800/60 border-slate-700/60">
            <CardHeader className="py-2 px-3">
              <CardTitle className="text-xs text-slate-300 flex items-center gap-1">
                <Plus className="w-3.5 h-3.5" /> Add Task
              </CardTitle>
            </CardHeader>
            <CardContent className="px-3 pb-3 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Input
                  value={newTask.name}
                  onChange={e => setNewTask(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="Task name"
                  className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8"
                />
                <Select
                  value={newTask.agent_id || '_none'}
                  onValueChange={v => setNewTask(prev => ({ ...prev, agent_id: v === '_none' ? '' : v }))}
                >
                  <SelectTrigger className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8">
                    <SelectValue placeholder="Select agent" />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-800 border-slate-700 text-slate-200">
                    <SelectItem value="_none">Auto-assign</SelectItem>
                    {registeredAgents.map(a => (
                      <SelectItem key={a} value={a}>{a}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Textarea
                value={newTask.description}
                onChange={e => setNewTask(prev => ({ ...prev, description: e.target.value }))}
                placeholder="Task description (prompt for agent)..."
                className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-16 resize-none placeholder:text-slate-600"
              />
              <Button
                size="sm"
                className="w-full bg-cyan-700 hover:bg-cyan-600 text-white h-8 text-xs transition-colors"
                onClick={addTask}
                disabled={!newTask.name.trim() || !newTask.description.trim()}
              >
                <Plus className="w-3.5 h-3.5 mr-1" /> Add Task
              </Button>
            </CardContent>
          </Card>

          {/* Task List */}
          {tasks.length > 0 && (
            <div className="space-y-2">
              <Label className="text-xs text-slate-400">Tasks ({tasks.length})</Label>
              {tasks.map((t, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 p-2.5 rounded bg-slate-800/60 border border-slate-700/50 group hover:border-slate-600/60 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-200 truncate">{t.name}</span>
                      {t.agent_id && (
                        <Badge variant="outline" className="text-[10px] py-0 px-1 bg-slate-700/60 text-slate-400 border-slate-600 shrink-0">
                          {t.agent_id}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{t.description}</p>
                  </div>
                  <button
                    onClick={() => removeTask(t.name)}
                    className="text-slate-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 shrink-0 mt-0.5"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Edges */}
          {tasks.length >= 2 && (
            <Card className="bg-slate-800/60 border-slate-700/60">
              <CardHeader className="py-2 px-3">
                <CardTitle className="text-xs text-slate-300 flex items-center gap-1">
                  <ArrowRight className="w-3.5 h-3.5" /> DAG Edges
                </CardTitle>
              </CardHeader>
              <CardContent className="px-3 pb-3 space-y-2">
                <div className="flex items-end gap-2">
                  <div className="flex-1 space-y-1 min-w-0">
                    <Label className="text-[10px] text-slate-500">From</Label>
                    <Select value={edgeFrom || '_none'} onValueChange={v => setEdgeFrom(v === '_none' ? '' : v)}>
                      <SelectTrigger className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8">
                        <SelectValue placeholder="From task" />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-800 border-slate-700 text-slate-200">
                        <SelectItem value="_none">-- Select --</SelectItem>
                        {tasks.map(t => (
                          <SelectItem key={t.name} value={t.name}>{t.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <span className="text-slate-600 mb-1.5 shrink-0">→</span>
                  <div className="flex-1 space-y-1 min-w-0">
                    <Label className="text-[10px] text-slate-500">To</Label>
                    <Select value={edgeTo || '_none'} onValueChange={v => setEdgeTo(v === '_none' ? '' : v)}>
                      <SelectTrigger className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8">
                        <SelectValue placeholder="To task" />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-800 border-slate-700 text-slate-200">
                        <SelectItem value="_none">-- Select --</SelectItem>
                        {tasks.map(t => (
                          <SelectItem key={t.name} value={t.name}>{t.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    size="sm"
                    className="bg-slate-700 hover:bg-slate-600 text-white h-8 text-xs shrink-0 transition-colors"
                    onClick={addEdge}
                    disabled={!edgeFrom || !edgeTo}
                  >
                    <Plus className="w-3.5 h-3.5" />
                  </Button>
                </div>

                {edges.length > 0 && (
                  <div className="space-y-1 mt-2">
                    {edges.map((e, i) => (
                      <div key={i} className="flex items-center justify-between text-xs p-1.5 rounded bg-slate-900/50 group">
                        <span className="text-slate-300 truncate">
                          <span className="text-cyan-400">{e.from}</span>
                          <span className="text-slate-600 mx-1">→</span>
                          <span className="text-cyan-400">{e.to}</span>
                        </span>
                        <button
                          onClick={() => removeEdge(i)}
                          className="text-slate-600 hover:text-red-400 opacity-0 group-hover:opacity-100 shrink-0 ml-1"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* DAG Preview */}
          {tasks.length > 0 && (
            <WorkflowDAG
              execution={null}
              preview
              previewTasks={tasks.map(t => ({ name: t.name, agent_id: t.agent_id || '', requires_approval: t.requires_approval }))}
              previewEdges={edges}
            />
          )}

          {error && (
            <p className="text-xs text-red-400 bg-red-900/20 border border-red-700/30 rounded p-2">{error}</p>
          )}

          {/* Save Button */}
          <Button
            className="w-full bg-emerald-700 hover:bg-emerald-600 text-white h-9 transition-colors"
            onClick={handleSave}
            disabled={saving || tasks.length === 0}
          >
            <Save className="w-4 h-4 mr-1.5" />
            {saving ? 'Saving...' : 'Define Workflow'}
          </Button>
        </div>
      </ScrollArea>
    </div>
  );
}
