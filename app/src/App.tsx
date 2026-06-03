import { useState, useCallback, useEffect, useRef } from 'react';
import StatusBar from '@/components/StatusBar';
import AgentSidebar from '@/components/AgentSidebar';
import AgentDetail from '@/components/AgentDetail';
import InterventionPanel from '@/components/InterventionPanel';
import EventLog from '@/components/EventLog';
import WorkflowControl from '@/components/WorkflowControl';
import WorkflowBuilder from '@/components/WorkflowBuilder';
import WorkflowDAG from '@/components/WorkflowDAG';
import AgentConfig from '@/components/AgentConfig';
import WorkflowLauncher from '@/components/WorkflowLauncher';
import DemoTemplates from '@/components/DemoTemplates';
import HelpPanel from '@/components/HelpPanel';
import { useAgents, useAgentDetail, useSystemStatus, useEventStream, useWorkflow, useWorkflowExecution } from '@/hooks/useApi';
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
  const { tasks, progress, taskStates, refetch: refetchWorkflow } = useWorkflow(events);
  const { execution } = useWorkflowExecution(events);

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
      try {
        const saved = localStorage.getItem('monitor_selected_agent');
        if (saved && agentIds.includes(saved)) {
          setSelectedAgent(saved);
          hasAutoSelectedRef.current = true;
          return;
        }
      } catch {
        // localStorage may be disabled (privacy mode, iframe, etc.)
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
      try {
        localStorage.setItem('monitor_selected_agent', selectedAgent);
      } catch {
        // localStorage may be disabled
      }
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
      {activeTab === 'monitor' && tasks.length > 0 && (
        <WorkflowControl progress={progress} tasks={tasks} taskStates={taskStates} events={events} onRefresh={refetchWorkflow} />
      )}

      {/* Tab Navigation */}
      <div className="flex items-center justify-between border-b border-slate-700 bg-slate-800/30 px-2"
      >
        <div className="flex items-center gap-0.5"
        >
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
        <HelpPanel />
      </div>

      {/* Main Content */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {activeTab === 'monitor' && (
          <>
            {/* Left Sidebar: Agent List */}
            <div className="w-64 shrink-0 overflow-hidden">
              <AgentSidebar
                agents={agents}
                selectedId={selectedAgent}
                onSelect={setSelectedAgent}
                taskStates={taskStates}
              />
            </div>

            {/* Center: Agent Detail */}
            <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
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
              <div className="h-40 shrink-0 overflow-hidden">
                <EventLog events={events} connected={connected} onSelectAgent={setSelectedAgent} />
              </div>
            </div>

            {/* Right Panel: Intervention */}
            <div className="w-64 shrink-0 overflow-hidden">
              <InterventionPanel agentId={selectedAgent} />
            </div>
          </>
        )}

        {activeTab === 'builder' && (
          <div className="flex-1 flex min-h-0 overflow-hidden">
            {/* Left: Demo Templates + Workflow Builder */}
            <div className="w-72 shrink-0 border-r border-slate-700 flex flex-col overflow-hidden">
              <DemoTemplates onLoaded={(ids) => {
                ids.forEach(id => handleAgentRegistered(id));
                setActiveTab('monitor');
              }} />
              <div className="flex-1 min-h-0 overflow-hidden">
                <WorkflowBuilder registeredAgents={registeredAgents} />
              </div>
            </div>
            {/* Right: DAG (main) + Launcher (bottom) */}
            <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
              {/* Top: DAG Visualization */}
              <div className="flex-1 min-h-0 p-3 overflow-auto">
                <WorkflowDAG
                  execution={execution}
                  taskStates={taskStates}
                />
              </div>
              {/* Bottom: Launcher + Execution Status */}
              <div className="shrink-0 border-t border-slate-700/60 bg-slate-800/30">
                <WorkflowLauncher />
              </div>
            </div>
          </div>
        )}

        {activeTab === 'config' && (
          <div className="flex-1 flex min-h-0 overflow-hidden">
            {/* Left: Agent Config */}
            <div className="w-80 shrink-0 border-r border-slate-700 overflow-hidden">
              <AgentConfig
                onRegister={handleAgentRegistered}
                registeredAgents={registeredAgents}
              />
            </div>
            {/* Right: Config Info */}
            <div className="flex-1 flex items-center justify-center text-slate-500 text-sm overflow-hidden">
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
