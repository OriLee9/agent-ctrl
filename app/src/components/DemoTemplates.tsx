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
      allowed_tools?: string[];
    }>;
    edges: Array<{ from: string; to: string }>;
  };
}

const DEMOS: DemoTemplate[] = [
  {
    id: 'racing',
    name: '3D Racing Game',
    description: 'Multi-agent: architect → coder → reviewer → Babylon.js single-file racing game',
    icon: <Car className="w-4 h-4" />,
    agents: [
      {
        agent_id: 'architect',
        temperature: 0.4,
        system_prompt: `You are a 3D game architect. Design browser-based games.

STRICT RULES:
- Output ONLY a markdown architecture document.
- NO code files. NO write_file(). NO HTML/JS/CSS blocks.
- Call done() with the complete design document.`,
      },
      {
        agent_id: 'coder',
        temperature: 0.6,
        max_iterations: 40,
        system_prompt: `You are a game developer. Write complete, working, single-file games.

ENGINE: Babylon.js v6 from CDN (https://cdn.jsdelivr.net/npm/babylonjs@6.49.0/babylon.js)
- Babylon.js provides: 3D rendering, scene graph, FollowCamera, ArcRotateCamera, built-in collision, particle system, GUI system
- Use ONLY Babylon.js APIs. Do NOT use Three.js.

OUTPUT RULES:
- Write ONE file only: index.html (all HTML + CSS + JS inline)
- NO ES modules. NO external .js files. Everything in one file.
- Every feature must have real implementation. NO placeholders.
- Call done() when index.html is complete.`,
      },
      {
        agent_id: 'reviewer',
        temperature: 0.2,
        max_iterations: 20,
        system_prompt: `You are a QA engineer. Review code ONCE, list ALL issues.

Rules:
1. Read design.md and index.html BEFORE writing feedback.
2. List EVERY issue in one pass. Do not stop at the first.
3. Only approve when 100% certain.
4. Call review_decision(approved=True) or review_decision(approved=False, feedback=...).`,
      },
    ],
    workflow: {
      name: 'racing_game',
      tasks: [
        {
          name: 'design',
          description: `Design a 3D arcade racing game.

Architecture plan (markdown only, no code):
1. ENGINE: Babylon.js v6 (CDN) — scene, camera, mesh collision, particles, GUI
2. FILE: Single index.html with inline CSS/JS
3. SCENE: Skybox, ground plane, track (spline/curve-based road with barriers)
4. CAR: Simple mesh (box body + 4 cylinder wheels), position/rotation updates
5. PHYSICS: Manual — acceleration, braking, steering angle, drift/friction, speed cap
6. CAMERA: FollowCamera (chase) + hotkey toggle to ArcRotateCamera
7. INPUT: W/S throttle/brake, A/D steer, Space handbrake, R reset, C camera toggle
8. STATES: Title screen → Countdown (3-2-1) → Racing → Lap complete / Finish → Results table
9. SCORING: 3 laps, lap timer, total time, best lap → localStorage persistence
10. UI: Speed HUD, lap counter, timer, minimap (top-down viewport)
11. EFFECTS: Skid marks (decal trails), dust particles when off-road
12. AUDIO: Web Audio API — engine pitch by RPM, crash noise, skid

CRITICAL: Output ONLY markdown. No code blocks.`,
          agent_id: 'architect',
          expected_output: 'Architecture plan',
          allowed_tools: ['done', 'think'],
        },
        {
          name: 'implement',
          description: `Build a COMPLETE 3D racing game as a SINGLE index.html file.

ENGINE: Babylon.js v6
  <script src="https://cdn.jsdelivr.net/npm/babylonjs@6.49.0/babylon.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/babylonjs-gui@6.49.0/babylon.gui.min.js"></script>

TOOLS: write_file(path, content), read_file_range(path)

REFERENCE: Read design.md for architecture details.

Write ONE file:
  write_file("index.html", "...")

index.html MUST contain ALL of the following inline:
- <style>: Full-screen canvas, HUD overlay (speed, lap, timer), title/results screens
- <script>: Babylon.js game code including:

  [1] Scene Setup
    - Create engine + canvas + scene
    - Skybox or gradient clear color
    - Directional light + hemispheric light
    - Shadow generator

  [2] Track
    - Build a closed-loop track using Babylon paths or positioned meshes
    - Road surface (flat box segments or extruded shape)
    - Barrier walls on both sides (use checkCollisions = true)
    - Start/finish line marker
    - Scenery: simple trees/bushes (cylinder + sphere) around track

  [3] Car
    - Body: Box mesh, colored material
    - 4 wheels: Cylinder meshes, parented to body
    - Position car at start line, facing track direction

  [4] Physics (manual — no physics engine needed)
    - speed, maxSpeed, acceleration, braking, friction
    - steering angle, turnSpeed, drift factor
    - Apply velocity to car position each frame
    - Simple collision: if car intersects barrier, bounce back slightly

  [5] Camera
    - FollowCamera: follows car from behind at offset
    - Press C to toggle to ArcRotateCamera (orbit view)

  [6] Input
    - W/S: throttle / brake
    - A/D: steer
    - Space: handbrake (reduce speed rapidly)
    - R: reset to last checkpoint
    - C: toggle camera

  [7] Game Loop / States
    - TITLE: Show title + "Press Enter to Start"
    - COUNTDOWN: 3-2-1 GO
    - RACING: Timer running, check lap completion
    - FINISHED: Show results (3 lap times + total + best)
    - Restart from results screen

  [8] Lap Detection
    - Define checkpoints around track (3-4 points)
    - Car must pass all checkpoints in order before finish line counts as lap
    - 3 laps total

  [9] HUD (DOM overlay or Babylon GUI)
    - Current speed (km/h)
    - Lap count (e.g. "Lap 2/3")
    - Current lap time
    - Best lap time

  [10] Audio
    - Engine sound: oscillator pitch varies with speed
    - Crash sound when hitting barrier
    - Skid sound during handbrake

  [11] Extras
    - localStorage: save best lap time, load on startup
    - FPS counter visible
    - Responsive canvas (resize handler)

FINAL STEP — Write IMPLEMENTATION_SUMMARY.md:
  write_file("IMPLEMENTATION_SUMMARY.md", "...") with:
  - Checklist of all 11 sections above — mark each as IMPLEMENTED or NOT IMPLEMENTED
  - Any deviations from design.md

CRITICAL:
- ONE file only: index.html
- NO external .js files, NO ES modules
- All Babylon.js code uses the global BABYLON object
- The game must be playable: car drives, laps count, timer works
- Call done() when index.html is written.`,
          agent_id: 'coder',
          expected_output: 'Complete index.html',
          max_passes: 2,
          review_gate: 'review',
        },
        {
          name: 'review',
          description: `Review the generated racing game. Read the files, then decide.

STEP 1 — Read:
  read_file_range("design.md")
  read_file_range("index.html")

STEP 2 — Check EVERY item below. List ALL issues found.

  [Track]
  - Is there a visible track with road and barriers?
  - Can the car drive on the track without falling through?

  [Car]
  - Does the car have a visible body + 4 wheels?
  - Does it move when W/S/A/D is pressed?

  [Physics]
  - Does speed increase with W, decrease with S/Space?
  - Is there a speed cap?
  - Does steering work?
  - Is there friction/drift?

  [Camera]
  - Does a follow camera track the car?
  - Does C toggle camera mode?

  [Lap System]
  - Are there 3 laps?
  - Does the lap counter increment?
  - Is there a timer per lap?

  [HUD]
  - Is speed displayed?
  - Is lap count displayed?
  - Is timer displayed?

  [States]
  - Title screen → countdown → race → finish flow works?

  [Audio]
  - Any engine/crash/skid sound?

  [Code Quality]
  - No syntax errors?
  - No undefined variables?
  - Babylon.js APIs used correctly?

STEP 3 — Verdict:
  review_decision(approved=True) — ONLY if all checks pass
  review_decision(approved=False, feedback=complete_issue_list) — if ANY issue`,
          agent_id: 'reviewer',
          expected_output: 'Review report',
          allowed_tools: ['done', 'think', 'read_file_range', 'review_decision'],
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
Output detailed plans: game mechanics, visual design, file structure, core systems, controls, scoring.

STRICT OUTPUT RULES — DESIGN MODE ONLY:
- You MUST output ONLY a markdown architecture document.
- You MUST NOT write any code files. DO NOT use write_file() or any file tools.
- You MUST NOT include HTML, JavaScript, or CSS code blocks in your output.
- Your output must be a pure design/architecture document with explanations and plans.
- Call done() with your complete design document when finished.`,
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
        max_iterations: 25,
        system_prompt: `You are a senior QA engineer. Your goal is to review code ONCE and list ALL issues in a single pass.

Rules:
1. Read ALL reference files (design.md + IMPLEMENTATION_SUMMARY.md + source files) before writing any feedback.
2. List EVERY issue you find in ONE comprehensive list. Do NOT stop at the first issue.
3. Only call review_decision(approved=True) when you are 100% certain everything is correct.
4. If ANY issue exists, call review_decision(approved=False) with the complete list.`,
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

CRITICAL: Output ONLY a markdown architecture document.
DO NOT write any code files. DO NOT use write_file() or any file tools.
DO NOT include HTML, JavaScript, or CSS code blocks.
Your output must be a pure design/architecture document.`,
          agent_id: 'architect',
          expected_output: 'Game design document',
          allowed_tools: ['done', 'think'],
        },
        {
          name: 'implement',
          description: `Build the COMPLETE innovative Snake game as a single index.html file.

TOOLS AVAILABLE:
- write_file(path, content) → write source files
- read_file_range(path)     → read existing files

REFERENCE: The full architecture design document is at design.md — read it if you need details.

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

FINAL STEP — Write IMPLEMENTATION_SUMMARY.md:
  After index.html is written, call write_file("IMPLEMENTATION_SUMMARY.md", "...") with:
  - Checklist of every design requirement and whether it is implemented
  - Any known issues or deviations from the design doc

CRITICAL:
- Every function MUST have real implementation. NO placeholders, NO stubs, NO TODO.
- The game MUST be fully playable with all features working.
- Single file only. After writing, verify the file is complete.`,
          agent_id: 'coder',
          expected_output: 'Complete index.html',
          max_passes: 2,
          review_gate: 'review',
        },
        {
          name: 'review',
          description: `Review the generated Snake game against the design spec — ONE PASS, list ALL issues.

STEP 1 — Read reference documents:
  read_file_range("design.md")
  read_file_range("IMPLEMENTATION_SUMMARY.md")

STEP 2 — Read source file:
  read_file_range("index.html")

STEP 3 — Compile ONE comprehensive issue list:
- Check EVERY requirement from the design doc (warp, dash, obstacles, combo, power-ups, particles, shake, difficulty, persistence, responsive, sound)
- List ALL issues found (not just the first one)
- Include line numbers if possible

STEP 4 — Submit verdict:
- If zero issues → review_decision(approved=True)
- If any issues → review_decision(approved=False, feedback=complete_list)

Do NOT call done(). Use review_decision() to submit your verdict.`,
          agent_id: 'reviewer',
          expected_output: 'Review report',
          allowed_tools: ['done', 'think', 'read_file_range', 'review_decision'],
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
