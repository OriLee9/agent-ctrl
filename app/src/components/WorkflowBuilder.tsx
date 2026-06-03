import { useState, useCallback, useEffect, useRef } from 'react';
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
import {
  saveWorkflowHistory,
  loadWorkflowHistory,
  deleteWorkflowHistory,
  type WorkflowHistoryItem,
} from '@/lib/workflowHistory';
import {
  Plus,
  Trash2,
  ArrowRight,
  Save,
  GitBranch,
  FilePlus,
  History,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  X,
} from 'lucide-react';

interface Props {
  registeredAgents: string[];
}

export default function WorkflowBuilder({ registeredAgents }: Props) {
  const { definition, refetch } = useWorkflowDefinition();
  const [wfName, setWfName] = useState('my_workflow');
  const [wfMode, setWfMode] = useState<'free' | 'fixed'>('free');
  const [tasks, setTasks] = useState<TaskDef[]>([]);
  const [edges, setEdges] = useState<EdgeDef[]>([]);

  // New Task form state
  const [newTask, setNewTask] = useState<TaskDef>(({
    name: '',
    description: '',
    agent_id: '',
  }));
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advancedFields, setAdvancedFields] = useState({
    requires_approval: false,
    max_retries: 2,
    temperature: undefined as number | undefined,
    review_gate: '',
    max_passes: 1,
  });

  const [edgeFrom, setEdgeFrom] = useState('');
  const [edgeTo, setEdgeTo] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // History dropdown
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyList, setHistoryList] = useState<WorkflowHistoryItem[]>([]);
  const historyRef = useRef<HTMLDivElement>(null);

  // Load history list when dropdown opens
  useEffect(() => {
    if (historyOpen) {
      setHistoryList(loadWorkflowHistory());
    }
  }, [historyOpen]);

  // Click outside to close history dropdown
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setHistoryOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Sync from backend definition
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
          review_gate: t.review_gate ? String(t.review_gate) : undefined,
          max_passes: t.max_passes as number | undefined,
        })));
      } else {
        setTasks([]);
      }
      if (wf.edges && wf.edges.length > 0) {
        setEdges(wf.edges.map((e: { from?: string; to?: string }) => ({
          from: e.from || '',
          to: e.to || '',
        })));
      } else {
        setEdges([]);
      }
    }
  }, [definition?.defined, definition?.workflow?.workflow_id]);

  const addTask = useCallback(() => {
    if (!newTask.name.trim() || !newTask.description.trim()) return;
    const task: TaskDef = {
      ...newTask,
      requires_approval: advancedFields.requires_approval || undefined,
      max_retries: advancedFields.max_retries || undefined,
      temperature: advancedFields.temperature,
      review_gate: advancedFields.review_gate || undefined,
      max_passes: advancedFields.max_passes > 1 ? advancedFields.max_passes : undefined,
    };
    setTasks(prev => [...prev, task]);
    setNewTask({ name: '', description: '', agent_id: '' });
    setAdvancedFields({
      requires_approval: false,
      max_retries: 2,
      temperature: undefined,
      review_gate: '',
      max_passes: 1,
    });
    setShowAdvanced(false);
  }, [newTask, advancedFields]);

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
  }, [wfName, tasks, edges, wfMode, refetch]);

  const handleSaveLocal = useCallback(() => {
    if (tasks.length === 0) return;
    saveWorkflowHistory({
      name: wfName,
      mode: wfMode,
      tasks,
      edges,
    });
    setHistoryList(loadWorkflowHistory());
  }, [wfName, wfMode, tasks, edges]);

  const handleNew = useCallback(() => {
    setWfName('my_workflow');
    setWfMode('free');
    setTasks([]);
    setEdges([]);
    setNewTask({ name: '', description: '', agent_id: '' });
    setError('');
  }, []);

  const handleLoadHistory = useCallback((item: WorkflowHistoryItem) => {
    setWfName(item.name);
    setWfMode(item.mode);
    setTasks(item.tasks);
    setEdges(item.edges);
    setHistoryOpen(false);
    setError('');
  }, []);

  const handleDeleteHistory = useCallback((id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    deleteWorkflowHistory(id);
    setHistoryList(loadWorkflowHistory());
  }, []);

  const hasDefinition = definition?.defined && definition?.workflow;

  // Other task names for review_gate dropdown
  const otherTaskNames = tasks.map(t => t.name);

  return (
    <div className="h-full flex flex-col">
      {/* ── Top Action Bar ── */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700/80 bg-slate-800/50 gap-2">
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs text-slate-300 hover:text-white hover:bg-slate-700"
            onClick={handleNew}
            title="New workflow"
          >
            <FilePlus className="w-3.5 h-3.5 mr-1" /> New
          </Button>

          {/* History Dropdown */}
          <div className="relative" ref={historyRef}>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-xs text-slate-300 hover:text-white hover:bg-slate-700"
              onClick={() => setHistoryOpen(!historyOpen)}
            >
              <History className="w-3.5 h-3.5 mr-1" /> History
              <ChevronDown className={`w-3 h-3 ml-1 transition-transform ${historyOpen ? 'rotate-180' : ''}`} />
            </Button>
            {historyOpen && (
              <div className="absolute top-full left-0 mt-1 w-56 bg-slate-800 border border-slate-700 rounded-md shadow-lg z-50 py-1">
                {historyList.length === 0 ? (
                  <div className="px-3 py-2 text-xs text-slate-500">No saved workflows</div>
                ) : (
                  historyList.map(item => (
                    <div
                      key={item.id}
                      className="flex items-center justify-between px-3 py-1.5 hover:bg-slate-700/60 cursor-pointer group"
                      onClick={() => handleLoadHistory(item)}
                    >
                      <div className="min-w-0">
                        <div className="text-xs text-slate-200 truncate">{item.name}</div>
                        <div className="text-[10px] text-slate-500">
                          {item.tasks.length} tasks · {new Date(item.createdAt).toLocaleDateString()}
                        </div>
                      </div>
                      <button
                        className="text-slate-600 hover:text-red-400 opacity-0 group-hover:opacity-100 shrink-0 p-1"
                        onClick={(e) => handleDeleteHistory(item.id, e)}
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>

          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs text-slate-300 hover:text-white hover:bg-slate-700"
            onClick={handleSaveLocal}
            disabled={tasks.length === 0}
            title="Save to local history"
          >
            <Save className="w-3.5 h-3.5 mr-1" /> Save
          </Button>
        </div>

        {hasDefinition && (
          <Badge variant="outline" className="text-[10px] bg-emerald-900/30 text-emerald-400 border-emerald-700/60 shrink-0">
            {definition.workflow!.name}
          </Badge>
        )}
      </div>

      <ScrollArea className="flex-1">
        <div className="p-3 space-y-4">
          {/* ── Workflow Name + Mode ── */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-slate-400">Name</Label>
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
              className="bg-slate-900 border-slate-700 text-slate-200 text-sm h-8"
              placeholder="my_workflow"
            />
          </div>

          {/* ── Add Task ── */}
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
                    <SelectValue placeholder="Agent" />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-800 border-slate-700 text-slate-200">
                    <SelectItem value="_none">Auto</SelectItem>
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
                className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-12 resize-none placeholder:text-slate-600"
              />

              {/* Advanced toggle */}
              <button
                className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
                onClick={() => setShowAdvanced(!showAdvanced)}
              >
                {showAdvanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                Advanced
              </button>

              {showAdvanced && (
                <div className="space-y-2 pt-1 border-t border-slate-700/40">
                  {/* Review Gate */}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label className="text-[10px] text-slate-500">Review Gate</Label>
                      <Select
                        value={advancedFields.review_gate || '_none'}
                        onValueChange={v => setAdvancedFields(prev => ({ ...prev, review_gate: v === '_none' ? '' : v }))}
                      >
                        <SelectTrigger className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8">
                          <SelectValue placeholder="None" />
                        </SelectTrigger>
                        <SelectContent className="bg-slate-800 border-slate-700 text-slate-200">
                          <SelectItem value="_none">None</SelectItem>
                          {otherTaskNames.map(name => (
                            <SelectItem key={name} value={name}>{name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[10px] text-slate-500">Max Passes</Label>
                      <Input
                        type="number"
                        min={1}
                        max={10}
                        value={advancedFields.max_passes}
                        onChange={e => setAdvancedFields(prev => ({ ...prev, max_passes: parseInt(e.target.value) || 1 }))}
                        className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8"
                      />
                    </div>
                  </div>
                  {/* Approval + Retries + Temperature */}
                  <div className="grid grid-cols-3 gap-2">
                    <div className="space-y-1">
                      <Label className="text-[10px] text-slate-500">Approval</Label>
                      <Select
                        value={advancedFields.requires_approval ? 'yes' : 'no'}
                        onValueChange={v => setAdvancedFields(prev => ({ ...prev, requires_approval: v === 'yes' }))}
                      >
                        <SelectTrigger className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-slate-800 border-slate-700 text-slate-200">
                          <SelectItem value="no">No</SelectItem>
                          <SelectItem value="yes">Yes</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[10px] text-slate-500">Retries</Label>
                      <Input
                        type="number"
                        min={0}
                        max={5}
                        value={advancedFields.max_retries}
                        onChange={e => setAdvancedFields(prev => ({ ...prev, max_retries: parseInt(e.target.value) || 0 }))}
                        className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[10px] text-slate-500">Temp</Label>
                      <Input
                        type="number"
                        min={0}
                        max={2}
                        step={0.1}
                        value={advancedFields.temperature ?? ''}
                        onChange={e => setAdvancedFields(prev => ({ ...prev, temperature: e.target.value ? parseFloat(e.target.value) : undefined }))}
                        className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8"
                        placeholder="0.7"
                      />
                    </div>
                  </div>
                </div>
              )}

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

          {/* ── Task List ── */}
          {tasks.length > 0 && (
            <div className="space-y-1.5">
              <Label className="text-xs text-slate-400">Tasks ({tasks.length})</Label>
              {tasks.map((t, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 p-2 rounded bg-slate-800/60 border border-slate-700/50 group hover:border-slate-600/60 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-xs font-medium text-slate-200">{t.name}</span>
                      {t.agent_id && (
                        <Badge variant="outline" className="text-[10px] py-0 px-1 bg-slate-700/60 text-slate-400 border-slate-600 shrink-0">
                          {t.agent_id}
                        </Badge>
                      )}
                      {t.review_gate && (
                        <Badge variant="outline" className="text-[10px] py-0 px-1 bg-orange-900/30 text-orange-400 border-orange-700/60 shrink-0">
                          R: {t.review_gate}
                        </Badge>
                      )}
                      {t.max_passes && t.max_passes > 1 && (
                        <Badge variant="outline" className="text-[10px] py-0 px-1 bg-purple-900/30 text-purple-400 border-purple-700/60 shrink-0">
                          {t.max_passes}x
                        </Badge>
                      )}
                      {t.requires_approval && (
                        <Badge variant="outline" className="text-[10px] py-0 px-1 bg-rose-900/30 text-rose-400 border-rose-700/60 shrink-0">
                          appr
                        </Badge>
                      )}
                    </div>
                    <p className="text-[10px] text-slate-500 mt-0.5 line-clamp-2">{t.description}</p>
                  </div>
                  <button
                    onClick={() => removeTask(t.name)}
                    className="text-slate-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 shrink-0 mt-0.5"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* ── Edges ── */}
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
                    <Select value={edgeFrom || '_none'} onValueChange={v => setEdgeFrom(v === '_none' ? '' : v)}>
                      <SelectTrigger className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8">
                        <SelectValue placeholder="From" />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-800 border-slate-700 text-slate-200">
                        <SelectItem value="_none">From</SelectItem>
                        {tasks.map(t => (
                          <SelectItem key={t.name} value={t.name}>{t.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <span className="text-slate-600 mb-1.5 shrink-0">→</span>
                  <div className="flex-1 space-y-1 min-w-0">
                    <Select value={edgeTo || '_none'} onValueChange={v => setEdgeTo(v === '_none' ? '' : v)}>
                      <SelectTrigger className="bg-slate-900 border-slate-700 text-slate-200 text-xs h-8">
                        <SelectValue placeholder="To" />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-800 border-slate-700 text-slate-200">
                        <SelectItem value="_none">To</SelectItem>
                        {tasks.map(t => (
                          <SelectItem key={t.name} value={t.name}>{t.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    size="sm"
                    className="bg-slate-700 hover:bg-slate-600 text-white h-8 text-xs shrink-0 transition-colors px-2"
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

          {error && (
            <p className="text-xs text-red-400 bg-red-900/20 border border-red-700/30 rounded p-2">{error}</p>
          )}

          {/* ── Define Button ── */}
          <Button
            className="w-full bg-emerald-700 hover:bg-emerald-600 text-white h-9 transition-colors"
            onClick={handleSave}
            disabled={saving || tasks.length === 0}
          >
            <GitBranch className="w-4 h-4 mr-1.5" />
            {saving ? 'Saving...' : 'Define Workflow'}
          </Button>
        </div>
      </ScrollArea>
    </div>
  );
}
