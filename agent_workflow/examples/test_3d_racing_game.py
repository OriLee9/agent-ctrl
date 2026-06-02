"""
端到端极限测试 — 3D赛车游戏（Three.js）。

Workflow设计（6阶段精细分工）:
  [design]        → 游戏设计文档（机制、画面、3D场景规划）
  [develop_core]  → 核心引擎（Three.js场景、相机、渲染循环）
  [develop_track] → 赛道系统（道路生成、3D环境、天空盒）
  [develop_car]   → 车辆系统（3D模型、物理、控制、碰撞）
  [develop_ui]    → UI系统（HUD、菜单、分数、特效）
  [integrate]     → 整合所有模块为单个可运行HTML文件
  [review]        → 严格代码审查和评分

监控机制:
  - 每轮迭代实时打印进度
  - 卡死检测：30秒无新消息则告警
  - Token消耗追踪
  - 产物文件大小检查
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import sys
import time
import uuid
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import Agent, AgentConfig
from core.llm import DeepSeekLLM, Message
from core.memory import Conversation
from core.skill import Skill, SkillRegistry
from core.sub_agent import SubAgentManager
from core.tool import tool
from orchestration.context_hub import ContextHub
from orchestration.task import Task
from orchestration.workflow_v2 import TaskNode, WorkflowV2, WorkflowState, TaskState


# ── 输出目录 ──────────────────────────────────────────────────
OUTPUT_DIR = str(Path(__file__).parent / 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── 监控日志 ──────────────────────────────────────────────────

class TaskMonitor:
    """Task级实时监控器。"""

    def __init__(self, log_file: str | None = None):
        self.log_file = log_file
        self.start_time = time.time()
        self.last_activity = time.time()
        self.iteration_count = 0
        self.token_count = 0

    def log(self, msg: str, level: str = "INFO") -> None:
        """打印并记录日志。"""
        elapsed = time.time() - self.start_time
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level}] [{elapsed:6.1f}s] {msg}"
        print(line)
        if self.log_file:
            with open(self.log_file, "a") as f:
                f.write(line + "\n")
        self.last_activity = time.time()

    def check_stall(self, timeout: int = 60) -> bool:
        """检查是否卡死（超过timeout秒无活动）。"""
        idle = time.time() - self.last_activity
        if idle > timeout:
            self.log(f"STALL DETECTED: {idle:.0f}s without activity", "WARN")
            return True
        return False

    def log_step(self, agent_name: str, iteration: int, thought: str | None, action: dict | None) -> None:
        """记录Agent执行步骤。"""
        self.iteration_count += 1
        action_str = f"{action['tool_name']}({action['arguments'][:50]})" if action else "none"
        thought_preview = (thought or "")[:60] if thought else "none"
        self.log(f"Step #{self.iteration_count} | {agent_name} iter#{iteration} | action={action_str} | thought={thought_preview}")


# ── 工具 ──────────────────────────────────────────────────────

@tool
def save_file(filepath: str, content: str) -> str:
    """Save content to a file in the output directory."""
    full_path = os.path.join(OUTPUT_DIR, filepath)
    os.makedirs(os.path.dirname(full_path) if "/" in filepath else OUTPUT_DIR, exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Saved: {filepath} ({len(content)} chars, {content.count(chr(10))} lines)"


@tool
def read_file(filepath: str) -> str:
    """Read content from a file in the output directory."""
    full_path = os.path.join(OUTPUT_DIR, filepath)
    if not os.path.exists(full_path):
        return f"[ERROR] File not found: {filepath}"
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


@tool
def file_exists(filepath: str) -> str:
    """Check if a file exists in the output directory."""
    full_path = os.path.join(OUTPUT_DIR, filepath)
    return "true" if os.path.exists(full_path) else "false"


@tool
def list_files() -> str:
    """List all files in the output directory."""
    files = []
    for root, _, filenames in os.walk(OUTPUT_DIR):
        for f in filenames:
            relpath = os.path.relpath(os.path.join(root, f), OUTPUT_DIR)
            size = os.path.getsize(os.path.join(root, f))
            files.append(f"  {relpath}: {size} bytes")
    return "Files:\n" + "\n".join(sorted(files)) if files else "No files yet"


# ── 主测试 ────────────────────────────────────────────────────

def test_3d_racing_game():
    """3D赛车游戏极限测试。"""

    log_path = os.path.join(OUTPUT_DIR, "test.log")
    monitor = TaskMonitor(log_path)

    monitor.log("=" * 70)
    monitor.log("3D Racing Game — End-to-End Stress Test")
    monitor.log("=" * 70)

    # 1. 初始化LLM（延长超时）
    monitor.log("\n[INIT] Setting up DeepSeek LLM with extended timeout...")
    llm = DeepSeekLLM(
        api_key="sk-4af21c8a7b2a41dcae4481d22528dc42",
        model="deepseek-chat",
        timeout=300,  # 300秒超时
    )
    monitor.log(f"  LLM: {llm.model_id()}, timeout: 300s")

    # 2. ContextHub
    monitor.log("\n[INIT] Creating ContextHub...")
    hub = ContextHub()
    monitor.log(f"  ContextHub created")

    # 3. 创建Skill Registry
    monitor.log("\n[INIT] Registering Skills...")
    registry = SkillRegistry()

    # Skill: 游戏设计师
    registry.register(Skill(
        name="game_designer",
        description="Expert game designer for 3D browser racing games",
        system_prompt=(
            "You are an expert game designer specializing in 3D browser racing games using Three.js.\n"
            "Your designs are detailed, practical, and developer-friendly.\n"
            "You always output structured markdown documents.\n"
            "After completing the design, IMMEDIATELY call `done(result='Design complete')`."
        ),
        tools=[save_file],
    ))

    # Skill: 核心引擎开发者
    registry.register(Skill(
        name="engine_dev",
        description="Three.js core engine developer",
        system_prompt=(
            "You are an expert Three.js developer specializing in 3D game engines.\n"
            "You write production-quality, well-commented code.\n"
            "\n"
            "CRITICAL: Do NOT read previously created files. You have 1M context window.\n"
            "Just create your assigned module as a new file. The integrator will combine them.\n"
            "\n"
            "Code standards:\n"
            "- Use ES6+ syntax, JSDoc comments, requestAnimationFrame\n"
            "- Export all functions/classes as globals (e.g., window.initEngine = initEngine)\n"
            "- After saving your file, IMMEDIATELY call done()\n"
            "\n"
            "Module interface for other developers to reference:\n"
            "- initEngine(containerId) → {scene, camera, renderer, gameLoop}\n"
            "- createRoadSegment() → THREE.Group\n"
            "- updateCamera(targetPosition, dt)"
        ),
        tools=[save_file, file_exists, list_files],
    ))

    # Skill: 车辆物理开发者
    registry.register(Skill(
        name="car_dev",
        description="3D vehicle physics and controls developer",
        system_prompt=(
            "You are an expert in 3D vehicle physics and game controls.\n"
            "\n"
            "CRITICAL: Do NOT read previously created files. You have 1M context window.\n"
            "Just create your assigned module as a new file. The integrator will combine them.\n"
            "\n"
            "Controls: Arrow keys/WASD for steering, Space for brake/handbrake.\n"
            "Physics: acceleration, deceleration, drifting, collision response.\n"
            "Export as globals (e.g., window.Car = Car). After saving, IMMEDIATELY call done().\n"
            "\n"
            "Your Car class interface:\n"
            "- new Car(scene) → car instance\n"
            "- car.update(input, dt) → updates position/rotation\n"
            "- car.getPosition() → THREE.Vector3\n"
            "- car.getMesh() → THREE.Group (for collision detection)"
        ),
        tools=[save_file, file_exists, list_files],
    ))

    # Skill: UI开发者
    registry.register(Skill(
        name="ui_dev",
        description="Game UI and effects developer",
        system_prompt=(
            "You are an expert game UI developer.\n"
            "\n"
            "CRITICAL: Do NOT read previously created files. You have 1M context window.\n"
            "Just create your assigned module as a new file. The integrator will combine them.\n"
            "\n"
            "UI features: speedometer, mini-map, lap timer, score, menus.\n"
            "Visual effects: particle effects, screen shake, motion blur hints.\n"
            "Export as globals. After saving, IMMEDIATELY call done().\n"
            "\n"
            "Your UI module interface:\n"
            "- initUI() → creates HUD DOM elements\n"
            "- updateHUD(speed, score, time) → updates display\n"
            "- showScreen(screenName) → 'start' | 'game' | 'gameover'\n"
            "- createParticleEffect(type, position) → 'boost' | 'crash' | 'spark'"
        ),
        tools=[save_file, file_exists, list_files],
    ))

    # Skill: 整合工程师
    registry.register(Skill(
        name="integrator",
        description="Integration engineer — combines modules into final product",
        system_prompt=(
            "You are a senior integration engineer.\n"
            "Your job: read all module files and produce ONE complete, runnable index.html.\n"
            "\n"
            "INTEGRATION RULES:\n"
            "1. Read ALL .js files using read_file tool\n"
            "2. Inline everything into a single index.html (no external .js files)\n"
            "3. Three.js from CDN: https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js\n"
            "4. CSS in <style>, JS in <script> at end of body\n"
            "5. Remove all 'export' / 'import' statements — make everything global\n"
            "6. Ensure the game initializes and runs when the page loads\n"
            "7. NO placeholders, NO TODOs, NO stubs\n"
            "8. After saving index.html, IMMEDIATELY call done()"
        ),
        tools=[save_file, read_file, file_exists, list_files],
    ))

    # Skill: 代码审查
    registry.register(Skill(
        name="strict_reviewer",
        description="Strict code reviewer with scoring rubric",
        system_prompt=(
            "You are a strict technical lead reviewing a 3D racing game.\n"
            "Evaluate on these criteria (0-10 each):\n"
            "1. COMPLETENESS: Does the game actually run and play?\n"
            "2. 3D QUALITY: Is the 3D scene compelling? (lighting, textures, models)\n"
            "3. GAMEPLAY: Is it fun? (controls responsive, challenge appropriate)\n"
            "4. CODE QUALITY: Clean, commented, no hacks?\n"
            "5. POLISH: Particles, effects, transitions, UI polish?\n"
            "Provide specific issues and actionable fixes.\n"
            "After review, call `done(result='Review: SCORE=X/50 - findings...')`."
        ),
        tools=[read_file, file_exists],
    ))

    skills_info = registry.list_skills()
    monitor.log(f"  Registered {len(skills_info)} skills:")
    for s in skills_info:
        monitor.log(f"    - {s['name']}: {s['description']} ({s['tool_count']} tools)")

    # 4. 创建Agents（增加max_iterations）
    monitor.log("\n[INIT] Creating Agents with extended config...")

    agents_config = {"max_iterations": 20, "stop_on_tool_error": False}

    designer = Agent(llm=llm, tools=[save_file], config=AgentConfig(**agents_config), name="designer")
    registry.apply_to_agent("game_designer", designer)

    engine_dev = Agent(llm=llm, tools=[save_file, read_file, file_exists, list_files],
                       config=AgentConfig(**agents_config), name="engine_dev")
    registry.apply_to_agent("engine_dev", engine_dev)
    engine_dev.register_tool(SubAgentManager(engine_dev, hub).create_tool())

    car_dev = Agent(llm=llm, tools=[save_file, read_file, file_exists, list_files],
                    config=AgentConfig(**agents_config), name="car_dev")
    registry.apply_to_agent("car_dev", car_dev)
    car_dev.register_tool(SubAgentManager(car_dev, hub).create_tool())

    ui_dev = Agent(llm=llm, tools=[save_file, read_file, file_exists, list_files],
                   config=AgentConfig(**agents_config), name="ui_dev")
    registry.apply_to_agent("ui_dev", ui_dev)

    integrator = Agent(llm=llm, tools=[save_file, read_file, file_exists, list_files],
                       config=AgentConfig(**agents_config), name="integrator")
    registry.apply_to_agent("integrator", integrator)

    reviewer = Agent(llm=llm, tools=[read_file, file_exists],
                     config=AgentConfig(**agents_config), name="reviewer")
    registry.apply_to_agent("strict_reviewer", reviewer)

    monitor.log(f"  Created 6 agents with max_iterations={agents_config['max_iterations']}")

    # 5. 构建WorkflowV2
    monitor.log("\n[INIT] Building WorkflowV2...")

    wf = WorkflowV2("3d_racing_game")
    wf.register_agent("designer", designer)
    wf.register_agent("engine_dev", engine_dev)
    wf.register_agent("car_dev", car_dev)
    wf.register_agent("ui_dev", ui_dev)
    wf.register_agent("integrator", integrator)
    wf.register_agent("reviewer", reviewer)
    wf.set_hub(hub)

    # Task 1: 游戏设计
    wf.add_task(TaskNode(
        task=Task(name="design", description=(
            "Create a comprehensive design document for a 3D racing game called 'Neon Drift'.\n\n"
            "Save as 'design.md'. Include:\n"
            "1. Game overview: top-down 3D racing with neon aesthetic\n"
            "2. 3D scene design: track layout, environment, lighting (neon colors: cyan #00ffff, magenta #ff00ff, purple #8b00ff)\n"
            "3. Player vehicle: sleek futuristic car with neon glow trails\n"
            "4. Controls: Arrow keys/WASD to steer, Space for drift boost\n"
            "5. Track system: procedural infinite track with curves and elevation\n"
            "6. Game modes: Time Trial with checkpoint system\n"
            "7. Visual effects: neon glow, particle trails, speed lines\n"
            "8. UI/HUD: speedometer, timer, lap counter, mini-map\n"
            "9. Audio cues description (even if not implemented)\n"
            "10. Technical notes: Three.js approach, performance considerations\n\n"
            "After saving, call done immediately."
        )),
        agent_id="designer",
        description="Game design document",
    ))

    # Task 2: 核心引擎
    wf.add_task(TaskNode(
        task=Task(name="develop_core", description=(
            "Create 'core.js' — the Three.js engine module.\n"
            "This is a standalone file. Create it with save_file, then call done.\n\n"
            "Must include:\n"
            "- initEngine(containerId) → creates scene, camera (fov75), renderer\n"
            "- Dark background #0a0a1a with purple fog\n"
            "- Ambient + directional light\n"
            "- requestAnimationFrame game loop with delta time\n"
            "- Export everything as window.xxx globals\n"
            "\nDo NOT read other files. Just create core.js and call done."
        )),
        agent_id="engine_dev",
        description="Core 3D engine",
    ))

    # Task 3: 赛道系统
    wf.add_task(TaskNode(
        task=Task(name="develop_track", description=(
            "Create 'track.js' — the track and environment module.\n"
            "Standalone file. Use save_file, then call done.\n\n"
            "Must include:\n"
            "- Procedural infinite track: segments with curves and elevation\n"
            "- Neon environment: glowing pillars, buildings (box geometry + neon edges)\n"
            "- Colors: cyan #00ffff, magenta #ff00ff, purple #8b00ff\n"
            "- Export as window.xxx globals\n"
            "\nDo NOT read other files. Just create track.js and call done."
        )),
        agent_id="engine_dev",
        description="Track and environment",
    ))

    # Task 4: 车辆系统
    wf.add_task(TaskNode(
        task=Task(name="develop_car", description=(
            "Create 'car.js' — the player vehicle module.\n"
            "Standalone file. Use save_file, then call done.\n\n"
            "Must include:\n"
            "- Car class with physics: acceleration, maxSpeed, deceleration, drift\n"
            "- Visual: car from Three.js primitives with neon materials #00ffff #ff00ff\n"
            "- update(input, dt) method (input = {left, right, up, space})\n"
            "- getPosition() returns THREE.Vector3\n"
            "- Export as window.Car\n"
            "\nDo NOT read other files. Just create car.js and call done."
        )),
        agent_id="car_dev",
        description="Vehicle physics and controls",
    ))

    # Task 5: UI系统
    wf.add_task(TaskNode(
        task=Task(name="develop_ui", description=(
            "Create 'ui.js' — the UI and effects module.\n"
            "Standalone file. Use save_file, then call done.\n\n"
            "Must include:\n"
            "- initUI() creates HUD elements (speedometer, timer, score)\n"
            "- showScreen(name) switches 'start' | 'game' | 'gameover'\n"
            "- CSS for neon glow text effects (text-shadow with cyan/magenta)\n"
            "- Particle effect functions: createExplosion(), createSpeedLines()\n"
            "- Export as window.xxx globals\n"
            "\nDo NOT read other files. Just create ui.js and call done."
        )),
        agent_id="ui_dev",
        description="UI, HUD, and effects",
    ))

    # Task 6: 整合
    wf.add_task(TaskNode(
        task=Task(name="integrate", description=(
            "Create ONE complete 'index.html' by inlining all modules.\n\n"
            "STEP 1: Read these files with read_file():\n"
            "  read_file('core.js')\n"
            "  read_file('track.js')\n" 
            "  read_file('car.js')\n"
            "  read_file('ui.js')\n\n"
            "STEP 2: Create index.html containing:\n"
            "  - Three.js CDN in <head>\n"
            "  - ALL CSS from ui.js in <style>\n"
            "  - ALL JS code inlined in <script> at end of body\n"
            "  - Remove import/export, make everything global\n"
            "  - Game initializes on page load\n\n"
            "STEP 3: save_file('index.html', ...) then call done()\n"
            "\nDo NOT skip any file. Do NOT leave TODOs."
        )),
        agent_id="integrator",
        description="Integration into final HTML",
    ))

    # Task 7: 审查评分
    wf.add_task(TaskNode(
        task=Task(name="review", description=(
            "Strictly review the final 'index.html'. Evaluate:\n"
            "1. Does it open and run in a browser without errors? (0-10)\n"
            "2. Is the 3D scene compelling with neon aesthetic? (0-10)\n"
            "3. Are controls responsive and fun? (0-10)\n"
            "4. Is code quality production-grade? (0-10)\n"
            "5. Is there visual polish (effects, UI, transitions)? (0-10)\n\n"
            "List ALL bugs found with severity (CRITICAL/MAJOR/MINOR).\n"
            "Suggest specific fixes for each issue.\n"
            "After review, call done with total score out of 50."
        )),
        agent_id="reviewer",
        description="Final review and scoring",
    ))

    monitor.log(f"  Workflow: {[t['name'] for t in wf.list_tasks()]}")

    # 6. 设置监控钩子
    monitor.log("\n[EXEC] Starting Workflow execution...")
    monitor.log("=" * 70)

    def on_task_start(name: str, node):
        monitor.log(f"\n{'='*50}")
        monitor.log(f"TASK START: {name} | Agent: {node.agent_id}")
        monitor.log(f"{'='*50}")

    def on_task_complete(name: str, exec_record):
        status_icon = "OK" if exec_record.state.value == "completed" else "FAIL"
        monitor.log(f"\nTASK END: {name} [{status_icon}] | Time: {exec_record.elapsed:.1f}s | Output: {len(exec_record.output)} chars")
        if exec_record.error:
            monitor.log(f"  ERROR: {exec_record.error}", "ERROR")

    def on_state_change(state: WorkflowState):
        monitor.log(f"\n>>> Workflow state changed: {state.value}")

    wf.on_task_start = on_task_start
    wf.on_task_complete = on_task_complete
    wf.on_state_change = on_state_change

    # 7. 执行（带监控）
    total_start = time.time()
    execution = wf.run(hub=hub)
    total_elapsed = time.time() - total_start

    # 8. 结果汇总
    monitor.log("\n" + "=" * 70)
    monitor.log("EXECUTION COMPLETE")
    monitor.log("=" * 70)

    monitor.log(f"\nWorkflow State: {execution.state.value}")
    monitor.log(f"Total Time: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")
    monitor.log(f"Tasks: {len(execution.task_executions)}")

    success_count = sum(1 for t in execution.task_executions.values() if t.state.value == "completed")
    monitor.log(f"Success: {success_count}/{len(execution.task_executions)}")

    for name, rec in execution.task_executions.items():
        icon = "OK" if rec.state.value == "completed" else "FAIL"
        monitor.log(f"  [{icon}] {name}: {rec.elapsed:.1f}s | {len(rec.output)} chars")

    # ContextHub统计
    monitor.log(f"\nContextHub:")
    for aid in hub.list_agents():
        s = hub.agent_summary(aid)
        if s:
            monitor.log(f"  {aid}: {s['message_count']} msgs, {s['step_count']} steps, {s['total_usage']['total_tokens']} tokens")

    # 产物检查
    monitor.log(f"\nOutput Files:")
    for root, _, files in os.walk(OUTPUT_DIR):
        for f in sorted(files):
            if f == "test.log":
                continue
            fp = os.path.join(root, f)
            sz = os.path.getsize(fp)
            monitor.log(f"  {os.path.relpath(fp, OUTPUT_DIR)}: {sz:,} bytes")

    # index.html质量检查
    index_path = os.path.join(OUTPUT_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            content = f.read()

        checks = {
            "three.js/THREE": "three.js" in content.lower() or "THREE." in content,
            "canvas element": "<canvas" in content.lower() or "getContext" in content,
            "game loop (rAF)": "requestAnimationFrame" in content,
            "keyboard input": "keydown" in content.lower() or "keyup" in content.lower(),
            "car/vehicle": "car" in content.lower() or "vehicle" in content.lower(),
            "track/road": "track" in content.lower() or "road" in content.lower(),
            "neon style": "neon" in content.lower() or "#00ffff" in content or "#ff00ff" in content,
            "css styling": "<style>" in content,
            "no TODO": "TODO" not in content and "FIXME" not in content and "placeholder" not in content.lower(),
            "no mock/stub": "mock" not in content.lower() and "stub" not in content.lower(),
        }

        monitor.log(f"\nQuality Check ({sum(checks.values())}/{len(checks)} passed):")
        for check, passed in checks.items():
            icon = "PASS" if passed else "FAIL"
            monitor.log(f"  [{icon}] {check}")

    monitor.log("\n" + "=" * 70)
    monitor.log("TEST COMPLETE")
    monitor.log("=" * 70)

    return execution


if __name__ == "__main__":
    try:
        test_3d_racing_game()
    except Exception as e:
        print(f"\n[CRITICAL ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)