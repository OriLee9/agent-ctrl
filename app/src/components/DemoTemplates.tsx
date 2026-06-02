import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { agentRegister, workflowDefine, workflowStart } from '@/hooks/useApi';
import { Loader2, Rocket, Car, Zap } from 'lucide-react';

interface DemoTemplate {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  agents: Array<{
    agent_id: string;
    model?: string;
    temperature?: number;
    max_iterations?: number;
    system_prompt: string;
  }>;
  workflow: {
    name: string;
    tasks: Array<{
      name: string;
      description: string;
      agent_id: string;
      expected_output?: string;
      requires_approval?: boolean;
      review_gate?: string;
      max_passes?: number;
    }>;
    edges: Array<{ from: string; to: string }>;
  };
}

const DEMOS: DemoTemplate[] = [
  {
    id: 'racing',
    name: '3D Racing Game',
    description: 'Multi-agent: architect → coder → reviewer → complete Three.js game',
    icon: <Car className="w-4 h-4" />,
    agents: [
      {
        agent_id: 'architect',
        temperature: 0.5,
        system_prompt: `You are an expert 3D game architect. Plan the architecture for a 3D racing game.
Output a detailed plan: file structure, core systems, physics, rendering, track design, car model, camera, UI, state machine, scoring. Use structured markdown.`,
      },
      {
        agent_id: 'coder',
        temperature: 0.7,
        max_iterations: 30,
        system_prompt: `You are an expert game developer. Write complete, working code.
Use Three.js r128 from CDN: https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js

CRITICAL — Output as a multi-file project directly in the workspace:
1. Write ALL files directly in the current directory (workspace = project root):
   write_file("index.html", ...)
   write_file("game.js", ...)
   write_file("physics.js", ...)
   write_file("track.js", ...)
   write_file("renderer.js", ...)
   write_file("ui.js", ...)
   write_file("audio.js", ...)
2. Use ES modules with <script type="module"> — each .js file = one module
3. Every function must have real implementation. Target 60fps.
4. Clean, well-commented, professional code. NO placeholders.`,
      },
      {
        agent_id: 'reviewer',
        temperature: 0.3,
        max_iterations: 10,
        system_prompt: `You are a QA engineer. Review the generated code for bugs, performance, completeness.
Check: game playable? All features work? No errors?

If the code is ready and has no blocking issues, respond with exactly "APPROVED".
If there are issues that must be fixed, list them clearly. Do NOT say "APPROVED" if fixes are needed.`,
      },
    ],
    workflow: {
      name: 'racing_game',
      tasks: [
        {
          name: 'design',
          description: `Design a 3D racing game architecture.

Plan:
1. Single index.html with inline Three.js (CDN r128)
2. Core: game loop, physics (acceleration, braking, steering, collision)
3. Track: curved road, barriers, scenery (trees, buildings, mountains)
4. Car: procedural geometry model
5. Camera: chase cam + overhead minimap
6. UI: speedometer, lap timer, gear indicator, position
7. States: title → countdown → racing → finish → results
8. Scoring: lap times, best lap via localStorage
9. Effects: particles (dust, sparks), Web Audio engine sound
10. Controls: W/S speed, A/D steer, R reset, C camera toggle

Output the complete architecture plan as structured markdown.`,
          agent_id: 'architect',
          expected_output: 'Architecture plan',
        },
        {
          name: 'implement',
          description: `Build the COMPLETE 3D racing game as a multi-file project.

TOOLS AVAILABLE:
- write_file(path, content) → write source files
- read_file_range(path)     → read existing files

STEP: Write each module as a separate file directly in the workspace:
  write_file("index.html", "...")   # HTML + canvas + module imports
  write_file("game.js", "...")       # Game loop, state machine, orchestration
  write_file("physics.js", "...")    # Vehicle dynamics: acceleration, braking, steering, collision
  write_file("track.js", "...")      # Track geometry: road, curbs, barriers, scenery
  write_file("renderer.js", "...")   # Three.js scene, camera, lighting, post-processing
  write_file("ui.js", "...")         # HUD: speedometer, lap timer, minimap, gear indicator
  write_file("audio.js", "...")      # Web Audio engine sound, collision, skid

REQUIREMENTS PER MODULE:
- game.js: Title → countdown → race → finish loop, game state machine, FPS counter
- physics.js: Acceleration curves, braking force, steering angle, drag, drift detection, AABB collision
- track.js: Procedural curved road mesh, barriers, trees, buildings, mountains
- renderer.js: Three.js r128 CDN import, scene setup, chase camera, dynamic lighting, fog, shadows
- ui.js: Canvas overlay — speedometer dial, lap counter, timer, gear position, minimap
- audio.js: Web Audio API — engine RPM synth, collision thud, tire skid at high slip angle
- index.html: Canvas element, module map, loading screen, responsive viewport

CRITICAL:
- Every function MUST have real implementation. NO placeholders, NO stubs, NO "TODO".
- Use ES module imports (e.g., import { Game } from './game.js')
- Three.js loaded via CDN in index.html, referenced as global 'THREE'
- The game MUST be playable — real physics, real rendering, real audio
- Write ALL files. After writing each, say which file was written.`,
          agent_id: 'coder',
          expected_output: 'Complete index.html',
          max_passes: 3,
          review_gate: 'review',
        },
        {
          name: 'review',
          description: `Review the generated 3D racing game.

Check:
1. Playable? Controls work, physics feel right?
2. All features present? Track, car, camera, UI, sound, particles?
3. JavaScript errors? Missing refs, undefined vars?
4. Performance: smooth 60fps?
5. Code quality: structured, commented?
6. Three.js: correct API, cleanup?
7. HTML: valid, responsive?

List issues with line refs. Write "APPROVED" if ready.`,
          agent_id: 'reviewer',
          expected_output: 'Review report',
        },
      ],
      edges: [
        { from: 'design', to: 'implement' },
        { from: 'implement', to: 'review' },
      ],
    },
  },
  {
    id: 'snake',
    name: 'Innovative Snake',
    description: 'Multi-agent: architect → coder → reviewer → complete HTML5 Canvas snake game with innovative mechanics',
    icon: <Zap className="w-4 h-4" />,
    agents: [
      {
        agent_id: 'architect',
        temperature: 0.5,
        system_prompt: `You are a creative game designer and architect. Design innovative browser-based games.
Output detailed plans: game mechanics, visual design, file structure, core systems, controls, scoring. Use structured markdown.`,
      },
      {
        agent_id: 'coder',
        temperature: 0.7,
        max_iterations: 25,
        system_prompt: `You are an expert HTML5 Canvas game developer. Write complete, working, polished code.

CRITICAL — Output as a single-file project directly in the workspace:
1. Write the game as a single index.html file with inline CSS and JavaScript
2. Use HTML5 Canvas API for rendering
3. Every function must have real implementation. Target 60fps.
4. Clean, well-commented, professional code. NO placeholders.`,
      },
      {
        agent_id: 'reviewer',
        temperature: 0.3,
        max_iterations: 10,
        system_prompt: `You are a QA engineer. Review the generated code for bugs, performance, completeness.
Check: game playable? All features work? No errors?

If the code is ready and has no blocking issues, respond with exactly "APPROVED".
If there are issues that must be fixed, list them clearly. Do NOT say "APPROVED" if fixes are needed.`,
      },
    ],
    workflow: {
      name: 'snake_game',
      tasks: [
        {
          name: 'design',
          description: `Design an innovative HTML5 Canvas Snake game with the following creative mechanics:

1. **Warp Mode** — Snake can pass through walls and reappear from the opposite side
2. **Dash Boost** — Hold Space to accelerate (consumes tail length as fuel)
3. **Obstacle Spawning** — Random static obstacles appear as score increases
4. **Combo Chain** — Eating food within 2s of the previous grants bonus points
5. **Power-ups** — Random items spawn: Speed Up, Slow Down, Double Points, Invincibility (5s)
6. **Visual Polish** — Smooth animations, particle effects on eat, screen shake on wall hit (if not in warp mode), glow effects
7. **Progressive Difficulty** — Speed increases every 50 points, obstacles multiply
8. **Score Persistence** — localStorage high score
9. **Responsive Design** — Works on both desktop (keyboard) and mobile (touch swipe)

Output a detailed architecture plan as structured markdown.`,
          agent_id: 'architect',
          expected_output: 'Game design document',
        },
        {
          name: 'implement',
          description: `Build the COMPLETE innovative Snake game as a single index.html file.

TOOLS AVAILABLE:
- write_file(path, content) → write source files

Write the game as a SINGLE index.html file:
  write_file("index.html", "...")   # Complete game with inline CSS + JS

REQUIREMENTS:
- HTML5 Canvas for rendering (no external libraries)
- Smooth 60fps game loop using requestAnimationFrame
- Snake: smooth movement, warp through walls, dash boost with fuel gauge
- Food: spawning with random position (avoid snake body)
- Power-ups: 4 types with distinct visual effects and durations
- Obstacles: spawn at score milestones, visual warning before appearing
- Combo chain: timer-based, display combo multiplier on screen
- Particles: burst on eating food, trail on dash
- Screen shake: brief shake on hitting wall in non-warp mode
- UI: score, high score, combo counter, fuel gauge, power-up indicator
- Controls: Arrow keys / WASD for desktop, swipe for mobile
- Start screen + Game Over screen with restart
- localStorage for high score persistence
- Sound effects using Web Audio API (eat, crash, power-up, combo)

CRITICAL:
- Every function MUST have real implementation. NO placeholders, NO stubs, NO TODO.
- The game MUST be fully playable with all features working.
- Single file only. After writing, verify the file is complete.`,
          agent_id: 'coder',
          expected_output: 'Complete index.html',
          max_passes: 3,
          review_gate: 'review',
        },
        {
          name: 'review',
          description: `Review the generated Snake game.

Check:
1. Playable? Controls responsive, snake moves smoothly?
2. Warp mode working? Pass through walls correctly?
3. Dash boost working? Fuel consumption, visual feedback?
4. Power-ups all functional? Correct durations and effects?
5. Combo chain working? Timer and bonus points?
6. Obstacles spawning at correct milestones?
7. Sound effects present? Web Audio API correct?
8. Mobile touch controls working?
9. No JavaScript errors?
10. Single file? No external dependencies?

List issues with line refs. Write "APPROVED" if ready.`,
          agent_id: 'reviewer',
          expected_output: 'Review report',
        },
      ],
      edges: [
        { from: 'design', to: 'implement' },
        { from: 'implement', to: 'review' },
      ],
    },
  },
];

interface Props {
  onLoaded: (agents: string[]) => void;
}

export default function DemoTemplates({ onLoaded }: Props) {
  const [loadingDemo, setLoadingDemo] = useState<string | null>(null);
  const [demoStatus, setDemoStatus] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);

  const loadDemo = async (demo: DemoTemplate) => {
    setLoadingDemo(demo.id);
    setDemoStatus(null);

    try {
      const registered: string[] = [];
      for (const agent of demo.agents) {
        const res = await agentRegister({
          agent_id: agent.agent_id,
          temperature: agent.temperature,
          max_iterations: agent.max_iterations,
          system_prompt: agent.system_prompt,
          model: agent.model,
          workflow_name: demo.workflow.name,
        });
        if (res.error) {
          setDemoStatus({ type: 'error', msg: `Agent "${agent.agent_id}": ${res.error}` });
          return;
        }
        registered.push(agent.agent_id);
      }

      const res = await workflowDefine(
        demo.workflow.name,
        demo.workflow.tasks,
        demo.workflow.edges,
      );
      if (res.error) {
        setDemoStatus({ type: 'error', msg: `Workflow: ${res.error}` });
        return;
      }

      const startRes = await workflowStart();
      if (startRes.error) {
        setDemoStatus({
          type: 'error',
          msg: `Workflow defined but start failed: ${String(startRes.error)}`,
        });
        return;
      }

      setDemoStatus({
        type: 'success',
        msg: `Demo running! ${demo.agents.length} agents, ${demo.workflow.tasks.length} tasks. Switch to Monitor tab to observe.`,
      });
      onLoaded(registered);
    } catch (e) {
      setDemoStatus({ type: 'error', msg: String(e) });
    } finally {
      setLoadingDemo(null);
    }
  };

  return (
    <div className="border-b border-slate-700/80 bg-slate-800/30">
      <div className="px-4 py-3">
        <div className="flex items-center gap-2 mb-2">
          <Rocket className="w-4 h-4 text-amber-400" />
          <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Demo Templates</h3>
          <Badge variant="outline" className="text-[10px] py-0 px-1 bg-amber-900/20 text-amber-400 border-amber-700/50">
            Quick Start
          </Badge>
        </div>

        <div className="flex flex-wrap gap-2">
          {DEMOS.map(demo => (
            <Button
              key={demo.id}
              size="sm"
              variant="outline"
              className="border-slate-600 text-slate-300 hover:bg-slate-700 hover:text-white h-auto py-2 px-3 text-xs transition-colors"
              onClick={() => loadDemo(demo)}
              disabled={loadingDemo !== null}
            >
              {loadingDemo === demo.id ? (
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
              ) : (
                demo.icon
              )}
              <span className="ml-1.5">{demo.name}</span>
            </Button>
          ))}
        </div>

        {demoStatus && (
          <div className={`mt-2 text-xs rounded p-2 border ${
            demoStatus.type === 'success'
              ? 'text-emerald-400 bg-emerald-900/20 border-emerald-700/30'
              : 'text-red-400 bg-red-900/20 border-red-700/30'
          }`}>
            {demoStatus.msg}
          </div>
        )}
      </div>
    </div>
  );
}
