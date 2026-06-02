import { useState, useCallback, useEffect, useRef } from 'react';
import StatusBar from '@/components/StatusBar';
import AgentSidebar from '@/components/AgentSidebar';
import AgentDetail from '@/components/AgentDetail';
import InterventionPanel from '@/components/InterventionPanel';
import EventLog from '@/components/EventLog';
import WorkflowControl from '@/components/WorkflowControl';
import WorkflowBuilder from '@/components/WorkflowBuilder';
import AgentConfig from '@/components/AgentConfig';
import WorkflowLauncher from '@/components/WorkflowLauncher';
import DemoTemplates from '@/components/DemoTemplates';
import { useAgents, useAgentDetail, useSystemStatus, useEventStream, useWorkflow } from '@/hooks/useApi';
import { cn } from '@/lib/utils';
import { Monitor, Settings, GitBranch } from 'lucide-react';
import './App.css';

type TabId = 'monitor' | 'builder' | 'config';

function App() {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>('monitor');
  const [registeredAgents, setRegisteredAgents] = useState<string[]>([]);
  const { agents, refetch: refetchAgents } = useAgents();
  const { detail } = useAgentDetail(selectedAgent);
  const { status, refetch: refetchStatus } = useSystemStatus();
  const { events, connected } = useEventStream();
  const { tasks, progress, taskStates } = useWorkflow(events);

  const handleRefresh = useCallback(() => {
    refetchAgents();
    refetchStatus();
  }, [refetchAgents, refetchStatus]);

  const handleAgentRegistered = useCallback((agentId: string) => {
    setRegisteredAgents(prev => {
      if (prev.includes(agentId)) return prev;
      return [...prev, agentId];
    });
  }, []);

  // 自动选中逻辑：
  // 1. 从 localStorage 读取上次选择
  // 2. 如果上次选择的 agent 仍在列表中，优先选中
  // 3. 否则按活跃程度自动选择
  const hasAutoSelectedRef = useRef(false);
  useEffect(() => {
    const agentIds = agents.map(a => a.agent_id);

    // 如果当前选中的 agent 已不在列表中，清空
    if (selectedAgent && !agentIds.includes(selectedAgent)) {
      setSelectedAgent(null);
      hasAutoSelectedRef.current = false;
      return;
    }

    if (!selectedAgent && agents.length > 0 && !hasAutoSelectedRef.current) {
      // 尝试从 localStorage 恢复上次选择
      const saved = localStorage.getItem('monitor_selected_agent');
      if (saved && agentIds.includes(saved)) {
        setSelectedAgent(saved);
        hasAutoSelectedRef.current = true;
        return;
      }

      // 优先选中有消息/步骤的 agent（通常是 Task Conversation）
      const activeAgents = agents.filter(a => (a.message_count || 0) > 0 || (a.step_count || 0) > 0);
      const target = activeAgents.length > 0 ? activeAgents[0] : agents[0];
      setSelectedAgent(target.agent_id);
      hasAutoSelectedRef.current = true;
    }
  }, [agents, selectedAgent]);

  // 保存选择到 localStorage
  useEffect(() => {
    if (selectedAgent) {
      localStorage.setItem('monitor_selected_agent', selectedAgent);
    }
  }, [selectedAgent]);

  const tabDefs: { id: TabId; label: string; icon: React.ReactNode }[] = [
    { id: 'monitor', label: 'Monitor', icon: <Monitor className="w-4 h-4" /> },
    { id: 'builder', label: 'Builder', icon: <GitBranch className="w-4 h-4" /> },
    { id: 'config', label: 'Config', icon: <Settings className="w-4 h-4" /> },
  ];

  return (
    <div className="h-screen flex flex-col bg-slate-900 overflow-hidden">
      {/* Top Status Bar + Workflow Control */}
      <StatusBar status={status} onRefresh={handleRefresh} />
      {tasks.length > 0 && (
        <WorkflowControl progress={progress} tasks={tasks} taskStates={taskStates} events={events} />
      )}

      {/* Tab Navigation */}
      <div className="flex items-center border-b border-slate-700 bg-slate-800/30 px-2 gap-0.5">
        {tabDefs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors border-b-2 -mb-px',
              activeTab === tab.id
                ? 'text-cyan-400 border-cyan-400'
                : 'text-slate-500 border-transparent hover:text-slate-300 hover:border-slate-600',
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Main Content */}
      <div className="flex-1 flex min-h-0">
        {activeTab === 'monitor' && (
          <>
            {/* Left Sidebar: Agent List */}
            <AgentSidebar
              agents={agents}
              selectedId={selectedAgent}
              onSelect={setSelectedAgent}
              taskStates={taskStates}
            />

            {/* Center: Agent Detail */}
            <div className="flex-1 min-w-0 flex flex-col">
              {detail && detail.agent_id === selectedAgent ? (
                <AgentDetail key={selectedAgent} detail={detail} />
              ) : (
                <div className="flex-1 flex items-center justify-center text-slate-500">
                  <div className="text-center space-y-2">
                    <p className="text-lg font-medium text-slate-400">Select an agent to view details</p>
                    <p className="text-sm text-slate-600">
                      Agents will appear here once registered with the ContextHub
                    </p>
                  </div>
                </div>
              )}

              {/* Bottom: Event Stream */}
              <div className="h-48 shrink-0">
                <EventLog events={events} connected={connected} onSelectAgent={setSelectedAgent} />
              </div>
            </div>

            {/* Right Panel: Intervention */}
            <div className="w-64 shrink-0">
              <InterventionPanel agentId={selectedAgent} />
            </div>
          </>
        )}

        {activeTab === 'builder' && (
          <div className="flex-1 flex flex-col min-h-0">
            {/* Demo Templates */}
            <DemoTemplates
              onLoaded={(agents) => {
                agents.forEach(a => {
                  if (!registeredAgents.includes(a)) {
                    setRegisteredAgents(prev => [...prev, a]);
                  }
                });
                // Demo 启动后自动切换到 Monitor tab 以便观察可视化
                setActiveTab('monitor');
              }}
            />
            <div className="flex-1 flex min-h-0">
              {/* Left: Workflow Builder */}
              <div className="w-80 shrink-0 border-r border-slate-700">
                <WorkflowBuilder registeredAgents={registeredAgents} />
              </div>
            {/* Right: Launcher + Status */}
            <div className="flex-1 flex flex-col min-w-0">
              <WorkflowLauncher />
              <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
                <div className="text-center space-y-2">
                  <GitBranch className="w-8 h-8 text-slate-600 mx-auto" />
                  <p>Define tasks, add edges, then launch your workflow.</p>
                  <p className="text-xs text-slate-600">
                    The workflow engine supports DAG topology, parallel execution, checkpoint/resume, and approval gates.
                  </p>
                </div>
              </div>
            </div>
            </div>
          </div>
        )}

        {activeTab === 'config' && (
          <div className="flex-1 flex min-h-0">
            {/* Left: Agent Config */}
            <div className="w-80 shrink-0 border-r border-slate-700">
              <AgentConfig
                onRegister={handleAgentRegistered}
                registeredAgents={registeredAgents}
              />
            </div>
            {/* Right: Config Info */}
            <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
              <div className="text-center space-y-2 max-w-md">
                <Settings className="w-8 h-8 text-slate-600 mx-auto" />
                <p>Register agents with LLM configurations here.</p>
                <p className="text-xs text-slate-600">
                  Each agent gets its own LLM instance with configurable model, temperature, and max iterations.
                  The API key is shared across all agents.
                </p>
                <div className="mt-4 p-3 rounded bg-slate-800/40 border border-slate-700/30 text-left text-xs space-y-1">
                  <p className="text-slate-400 font-medium mb-1">Workflow Lifecycle:</p>
                  <p className="text-slate-500">1. <span className="text-purple-400">Config</span> — Register agents</p>
                  <p className="text-slate-500">2. <span className="text-cyan-400">Builder</span> — Define tasks + DAG edges</p>
                  <p className="text-slate-500">3. <span className="text-emerald-400">Launcher</span> — Start workflow execution</p>
                  <p className="text-slate-500">4. <span className="text-blue-400">Monitor</span> — Observe agent activity</p>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
