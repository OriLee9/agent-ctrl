import { useState, useRef, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import {
  HelpCircle,
  X,
  Settings,
  GitBranch,
  Play,
  Monitor,
  Save,
  Globe,
  HardDrive,
} from 'lucide-react';

export default function HelpPanel() {
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // Close on escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    if (open) {
      document.addEventListener('keydown', onKey);
      return () => document.removeEventListener('keydown', onKey);
    }
  }, [open]);

  // Click outside to close
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener('mousedown', onClick);
      return () => document.removeEventListener('mousedown', onClick);
    }
  }, [open]);

  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        className="h-7 px-2 text-xs text-slate-400 hover:text-white hover:bg-slate-700"
        onClick={() => setOpen(!open)}
        title="Help"
      >
        <HelpCircle className="w-3.5 h-3.5" />
      </Button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-center pt-[7.5vh] bg-black/50">
          <div
            ref={panelRef}
            className="w-[720px] max-w-[92vw] h-[85vh] bg-slate-800 border border-slate-700 rounded-lg shadow-2xl flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-700/80 shrink-0">
              <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                <HelpCircle className="w-4 h-4 text-cyan-400" />
                Workflow Builder Guide
              </h2>
              <button
                onClick={() => setOpen(false)}
                className="text-slate-500 hover:text-white transition-colors p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 min-h-0" style={{ overflowY: 'auto' }}>
              <div className="p-5 space-y-5 text-[13px] text-slate-300 leading-relaxed">

                {/* Lifecycle */}
                <section>
                  <h3 className="text-sm font-semibold text-slate-200 mb-2.5 flex items-center gap-1.5">
                    <Globe className="w-4 h-4 text-emerald-400" />
                    Workflow Lifecycle
                  </h3>
                  <div className="grid grid-cols-4 gap-2.5">
                    {[
                      { icon: <Settings className="w-3.5 h-3.5" />, label: 'Config', color: 'text-purple-400', desc: 'Register agents with LLM settings' },
                      { icon: <GitBranch className="w-3.5 h-3.5" />, label: 'Builder', color: 'text-cyan-400', desc: 'Define tasks & DAG edges' },
                      { icon: <Play className="w-3.5 h-3.5" />, label: 'Launcher', color: 'text-emerald-400', desc: 'Start workflow execution' },
                      { icon: <Monitor className="w-3.5 h-3.5" />, label: 'Monitor', color: 'text-blue-400', desc: 'Observe agent activity live' },
                    ].map((step, i) => (
                      <div key={i} className="text-center p-2.5 rounded-md bg-slate-900/50 border border-slate-700/50">
                        <div className={`${step.color} mb-1.5 flex justify-center`}>{step.icon}</div>
                        <div className="font-medium text-slate-200 text-xs">{step.label}</div>
                        <div className="text-[11px] text-slate-500 mt-1 leading-tight">{step.desc}</div>
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center justify-center gap-1.5 mt-2 text-[11px] text-slate-500 font-mono">
                    <span className="px-1.5 py-0.5 rounded bg-slate-900/50">1</span>
                    <span className="text-slate-600">→</span>
                    <span className="px-1.5 py-0.5 rounded bg-slate-900/50">2</span>
                    <span className="text-slate-600">→</span>
                    <span className="px-1.5 py-0.5 rounded bg-slate-900/50">3</span>
                    <span className="text-slate-600">→</span>
                    <span className="px-1.5 py-0.5 rounded bg-slate-900/50">4</span>
                  </div>
                </section>

                {/* New vs Define */}
                <section>
                  <h3 className="text-sm font-semibold text-slate-200 mb-2.5 flex items-center gap-1.5">
                    <Save className="w-4 h-4 text-amber-400" />
                    New vs Save vs Define Workflow
                  </h3>
                  <div className="space-y-2">
                    <div className="p-3 rounded-md bg-slate-900/50 border border-slate-700/50">
                      <div className="font-medium text-slate-200 text-xs mb-1">New</div>
                      <p className="text-slate-400 leading-relaxed">
                        Clears the current builder form and starts a blank workflow. This only affects the form — nothing is saved or sent to the server.
                      </p>
                    </div>
                    <div className="p-3 rounded-md bg-slate-900/50 border border-slate-700/50">
                      <div className="font-medium text-slate-200 text-xs mb-1 flex items-center gap-1.5">
                        <HardDrive className="w-3 h-3 text-slate-400" />
                        Save
                      </div>
                      <p className="text-slate-400 leading-relaxed">
                        Saves the current workflow definition to <strong>browser localStorage</strong>. Use this to keep a draft you can load later via the <strong>History</strong> dropdown. Saved workflows are private to this browser.
                      </p>
                    </div>
                    <div className="p-3 rounded-md bg-slate-900/50 border border-emerald-700/30">
                      <div className="font-medium text-emerald-400 text-xs mb-1">Define Workflow</div>
                      <p className="text-slate-400 leading-relaxed">
                        Sends the workflow definition to the <strong>backend server</strong>. This is the required step before you can launch the workflow. After defining, the green badge appears showing the workflow is active.
                      </p>
                    </div>
                  </div>
                </section>

                {/* Quick Start */}
                <section>
                  <h3 className="text-sm font-semibold text-slate-200 mb-2.5 flex items-center gap-1.5">
                    <Play className="w-4 h-4 text-emerald-400" />
                    Quick Start
                  </h3>
                  <ol className="space-y-2 list-decimal list-inside text-slate-400 leading-relaxed">
                    <li>Go to <strong className="text-purple-400">Config</strong> tab → Register your agents (architect, coder, reviewer) with LLM settings</li>
                    <li>Go to <strong className="text-cyan-400">Builder</strong> tab → Add tasks with names, descriptions, and assign agents</li>
                    <li>Connect tasks with <strong>DAG edges</strong> (e.g. design → implement → review)</li>
                    <li>Click <strong className="text-emerald-400">Define Workflow</strong> to send to backend</li>
                    <li>Go to <strong className="text-emerald-400">Launcher</strong> panel (bottom-right) → Click <strong>Start Workflow</strong></li>
                    <li>Switch to <strong className="text-blue-400">Monitor</strong> tab to watch agents work in real-time</li>
                  </ol>
                </section>

                {/* Demo Templates */}
                <section>
                  <h3 className="text-sm font-semibold text-slate-200 mb-2.5 flex items-center gap-1.5">
                    <GitBranch className="w-4 h-4 text-amber-400" />
                    Demo Templates
                  </h3>
                  <p className="text-slate-400 mb-2.5 leading-relaxed">
                    The Builder panel includes two pre-built demos for instant testing:
                  </p>
                  <div className="grid grid-cols-2 gap-2.5">
                    <div className="p-3 rounded-md bg-slate-900/50 border border-slate-700/50">
                      <div className="font-medium text-slate-200 text-xs">3D Racing Game</div>
                      <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">Three.js multi-file project with physics, track, car, audio</p>
                    </div>
                    <div className="p-3 rounded-md bg-slate-900/50 border border-slate-700/50">
                      <div className="font-medium text-slate-200 text-xs">Innovative Snake</div>
                      <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">HTML5 Canvas single-file with warp, dash, power-ups, combos</p>
                    </div>
                  </div>
                  <p className="text-slate-500 mt-2.5 leading-relaxed">
                    Click a demo button to auto-register agents, define the workflow, and start execution in one step.
                  </p>
                </section>

                {/* Task Settings */}
                <section>
                  <h3 className="text-sm font-semibold text-slate-200 mb-2.5 flex items-center gap-1.5">
                    <Settings className="w-4 h-4 text-slate-400" />
                    Advanced Task Settings
                  </h3>
                  <div className="space-y-2 text-slate-400 leading-relaxed">
                    <p><strong className="text-slate-300">Review Gate</strong> — Another task must approve this task before it completes. Enables multi-pass refinement.</p>
                    <p><strong className="text-slate-300">Max Passes</strong> — How many times the task can retry if review rejects it.</p>
                    <p><strong className="text-slate-300">Requires Approval</strong> — Task pauses and waits for human approval before continuing.</p>
                    <p><strong className="text-slate-300">Retries</strong> — Auto-retry count on failure (e.g. LLM timeout).</p>
                    <p><strong className="text-slate-300">Temperature</strong> — LLM creativity level for this specific task (overrides agent default).</p>
                  </div>
                </section>

                {/* Keyboard Shortcuts */}
                <section>
                  <h3 className="text-sm font-semibold text-slate-200 mb-2.5">Keyboard Shortcuts</h3>
                  <div className="grid grid-cols-2 gap-2 text-slate-400">
                    <div className="flex justify-between items-center px-3 py-2 rounded-md bg-slate-900/30">
                      <span>Close help panel</span>
                      <kbd className="px-2 py-0.5 rounded bg-slate-700 text-[11px] text-slate-300 font-mono">Esc</kbd>
                    </div>
                  </div>
                </section>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
