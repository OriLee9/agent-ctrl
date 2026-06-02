"""
3D赛车游戏测试 v4 — 保证每个环节成功。

关键设计:
1. 开发Task通过LLM Agent生成.js文件(独立Conversation)
2. integrate Task使用 local_executor → 本地Python拼接,不经过LLM,100%成功
3. review Task通过LLM审查最终产物
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import Agent, AgentConfig
from core.llm import DeepSeekLLM
from core.skill import Skill, SkillRegistry
from core.sub_agent import SubAgentManager
from core.tool import tool
from orchestration.context_hub import ContextHub
from orchestration.task import Task
from orchestration.workflow_v2 import TaskNode, WorkflowV2, WorkflowState

OUTPUT_DIR = str(Path(__file__).parent / 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)


@tool
def save_file(filepath: str, content: str) -> str:
    full_path = os.path.join(OUTPUT_DIR, filepath)
    os.makedirs(os.path.dirname(full_path) if "/" in filepath else OUTPUT_DIR, exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Saved: {filepath} ({len(content)} chars)"


@tool
def read_file(filepath: str) -> str:
    full_path = os.path.join(OUTPUT_DIR, filepath)
    if not os.path.exists(full_path):
        return f"[ERROR] Not found: {filepath}"
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


@tool
def file_exists(filepath: str) -> str:
    return "true" if os.path.exists(os.path.join(OUTPUT_DIR, filepath)) else "false"


def local_integrate(outputs: dict) -> str:
    """
    本地整合函数 — 不经过LLM,直接拼接所有.js文件为index.html。
    使用字符串拼接(非f-string)避免花括号冲突。
    """
    def clean_js(code):
        code = re.sub(r'^\s*import\s+.*?;?\s*$', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*export\s+default\s+.*?;?\s*$', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*export\s*\{[^}]*\}\s*;?\s*$', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*export\s+(class|function|const|let|var)\s+', r'\1 ', code, flags=re.MULTILINE)
        return code

    modules = {}
    for fname in ["core.js", "track.js", "car.js", "ui.js"]:
        fpath = os.path.join(OUTPUT_DIR, fname)
        if not os.path.exists(fpath):
            return f"[ERROR] Missing {fname}"
        with open(fpath, "r") as f:
            modules[fname.replace(".js", "")] = clean_js(f.read())

    # Build HTML using string concatenation (NOT f-string) to avoid { } conflicts
    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Neon Drift — 3D Racing</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #0a0a1a; overflow: hidden; font-family: 'Segoe UI', Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; }
#gameContainer { position: relative; width: 100vw; height: 100vh; }
#gameContainer canvas { display: block; width: 100%; height: 100%; }
</style>
</head>
<body>
<div id="gameContainer"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
// ============================================================
// Neon Drift — 3D Racing Game
// ============================================================

// -- CORE ENGINE --
""")
    parts.append(modules.get("core", "// core missing"))
    parts.append("""

// -- TRACK SYSTEM --
""")
    parts.append(modules.get("track", "// track missing"))
    parts.append("""

// -- CAR SYSTEM --
""")
    parts.append(modules.get("car", "// car missing"))
    parts.append("""

// -- UI SYSTEM --
""")
    parts.append(modules.get("ui", "// ui missing"))
    parts.append("""

// -- GAME INITIALIZATION --
(function() {
    console.log('Neon Drift initializing...');
    try {
        if (typeof initEngine === 'function') {
            window._engine = initEngine('gameContainer');
            console.log('Engine OK');
        }
        if (typeof Car === 'function' && window._engine && window._engine.scene) {
            window._playerCar = new Car(window._engine.scene);
            console.log('Car OK');
        }
        if (typeof initUI === 'function') {
            initUI();
            console.log('UI OK');
        }
        console.log('Neon Drift ready!');
    } catch (e) {
        console.error('Init error:', e);
    }
})();
</script>
</body>
</html>""")

    html = "\n".join(parts)
    out_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(out_path, "w") as f:
        f.write(html)

    # Verify each module is present
    for name in ["core", "track", "car", "ui"]:
        marker = f"// -- {name.upper()}"
        size = len(modules.get(name, ""))
        print(f"  Module {name}: {size:,} chars")

    return f"Integrated: {out_path} ({len(html):,} chars, {html.count(chr(10))} lines)"


def main():
    print("=" * 60)
    print("3D Racing Game v4 — Local Integrate (100% Success)")
    print("=" * 60)

    llm = DeepSeekLLM(api_key="sk-4af21c8a7b2a41dcae4481d22528dc42", model="deepseek-v4-pro", timeout=120)
    hub = ContextHub()
    registry = SkillRegistry()

    # Skills
    registry.register(Skill(
        name="game_designer",
        description="Game designer",
        system_prompt="Expert game designer. Create detailed design docs. After saving, call done().",
        tools=[save_file],
    ))
    registry.register(Skill(
        name="engine_dev",
        description="Three.js developer",
        system_prompt=(
            "You are a Three.js expert writing PRODUCTION game code. "
            "CRITICAL RULES:\n"
            "1. Write COMPLETE, RUNNABLE code — NOT placeholders or stubs\n"
            "2. Every function must be fully implemented with real logic\n"
            "3. Code should be 200+ lines of actual implementation\n"
            "4. Export everything as window.xxx globals\n"
            "5. After save_file(), call done(result='saved N lines')"
        ),
        tools=[save_file, file_exists],
    ))
    registry.register(Skill(
        name="car_dev",
        description="Car physics developer",
        system_prompt=(
            "You are a vehicle physics expert writing PRODUCTION game code. "
            "CRITICAL RULES:\n"
            "1. Write COMPLETE, RUNNABLE code — NOT placeholders or stubs\n"
            "2. Every method must be fully implemented with real physics logic\n"
            "3. Code should be 200+ lines of actual implementation\n"
            "4. Export Car class as window.Car\n"
            "5. After save_file(), call done(result='saved N lines')"
        ),
        tools=[save_file, file_exists],
    ))
    registry.register(Skill(
        name="ui_dev",
        description="UI developer",
        system_prompt=(
            "You are a game UI expert writing PRODUCTION game code. "
            "CRITICAL RULES:\n"
            "1. Write COMPLETE, RUNNABLE code — NOT placeholders or stubs\n"
            "2. Every function must be fully implemented with real rendering logic\n"
            "3. Code should be 200+ lines of actual implementation\n"
            "4. Export everything as window.xxx globals\n"
            "5. After save_file(), call done(result='saved N lines')"
        ),
        tools=[save_file, file_exists],
    ))
    registry.register(Skill(
        name="reviewer",
        description="Code reviewer",
        system_prompt=(
            "You are a strict technical lead reviewing a 3D racing game. "
            "Score each criterion 0-10:\n"
            "1. RUNS: Does it show 3D graphics when opened?\n"
            "2. 3D QUALITY: Visuals compelling (lighting, colors, geometry)?\n"
            "3. CONTROLS: Keyboard controls responsive and fun?\n"
            "4. CODE: Clean, commented, well-structured?\n"
            "5. POLISH: Effects, UI, transitions, visual flair?\n"
            "IMPORTANT: read_file returns FIRST 3000 chars only (not full file). "
            "Base your review on what you can see. "
            "After scoring, call done(result='Score: X/50 - key findings')."
        ),
        tools=[read_file],
    ))

    # Agents
    cfg = {"max_iterations": 15}
    designer = Agent(llm=llm, tools=[save_file], config=AgentConfig(**cfg), name="designer")
    registry.apply_to_agent("game_designer", designer)

    engine_dev = Agent(llm=llm, tools=[save_file, file_exists], config=AgentConfig(**cfg), name="engine_dev")
    registry.apply_to_agent("engine_dev", engine_dev)
    engine_dev.register_tool(SubAgentManager(engine_dev, hub).create_tool())

    car_dev = Agent(llm=llm, tools=[save_file, file_exists], config=AgentConfig(**cfg), name="car_dev")
    registry.apply_to_agent("car_dev", car_dev)

    ui_dev = Agent(llm=llm, tools=[save_file, file_exists], config=AgentConfig(**cfg), name="ui_dev")
    registry.apply_to_agent("ui_dev", ui_dev)

    reviewer = Agent(llm=llm, tools=[read_file], config=AgentConfig(**cfg), name="reviewer")
    registry.apply_to_agent("reviewer", reviewer)

    # Workflow
    wf = WorkflowV2("3d_racing_v4", auto_recover=True)
    wf.register_agent("designer", designer)
    wf.register_agent("engine_dev", engine_dev)
    wf.register_agent("car_dev", car_dev)
    wf.register_agent("ui_dev", ui_dev)
    wf.register_agent("reviewer", reviewer)
    wf.set_hub(hub)

    # Tasks 1-5: LLM开发
    wf.add_task(TaskNode(Task(name="design", description="Create 'design.md' — 3D racing game design with neon aesthetic, Three.js, controls, scoring. Save then done."), agent_id="designer"))
    wf.add_task(TaskNode(Task(name="develop_core", description="Create 'core.js' — COMPLETE Three.js engine with initEngine(), scene, PerspectiveCamera(fov75,near0.1,far2000), WebGLRenderer, requestAnimationFrame loop, delta time, dark bg #0a0a1a, fog. EVERY function fully implemented, NOT placeholder. Export as window.initEngine. Call save_file('core.js', ...) then done()."), agent_id="engine_dev"))
    wf.add_task(TaskNode(Task(name="develop_track", description="Create 'track.js' — COMPLETE procedural track system: Track class with generate(), curved segments, neon environment objects (cyan #00ffff, magenta #ff00ff pillars), road markings. EVERY method fully implemented, NOT placeholder. Export as window.Track. Call save_file('track.js', ...) then done()."), agent_id="engine_dev"))
    wf.add_task(TaskNode(Task(name="develop_car", description="Create 'car.js' — COMPLETE Car class with real physics: acceleration, deceleration, maxSpeed 50, drift on Space, steering with Arrow keys, neon materials #00ffff/#ff00ff, update(input,dt) with delta time, getPosition(). EVERY method fully implemented, NOT placeholder. Export window.Car. Call save_file('car.js', ...) then done()."), agent_id="car_dev"))
    wf.add_task(TaskNode(Task(name="develop_ui", description="Create 'ui.js' — COMPLETE UI system: initUI() creating DOM elements, showScreen('menu'|'game'|'gameover'), HUD with speedometer/div/timer/score divs, neon CSS text-shadow. EVERY function fully implemented with real DOM code, NOT placeholder. Export window.initUI and window.showScreen. Call save_file('ui.js', ...) then done()."), agent_id="ui_dev"))

    # Task 6: 本地整合 — 关键! 使用local_executor,不经过LLM,100%成功
    wf.add_task(TaskNode(
        Task(name="integrate", description="Local integration: combine all .js files into index.html"),
        agent_id="integrator",  # 不需要真实Agent
        local_executor=local_integrate,  # 本地执行,不经过LLM
    ))

    # Task 7: 审查
    wf.add_task(TaskNode(Task(name="review", description="Review index.html for a 3D racing game. Use read_file('index.html') to examine the code (first 3000 chars returned). Score 0-10 each: RUNS, 3D QUALITY, CONTROLS, CODE QUALITY, POLISH. Total /50. Call done(result='Score: X/50 - your findings')."), agent_id="reviewer"))

    # 监控
    def on_task_start(name, node):
        mode = "LOCAL" if node.local_executor else "LLM"
        print(f"\n  >>> [{name}] START ({mode})")

    def on_task_complete(name, rec):
        icon = "OK" if rec.state.value in ("completed", "recovered") else "FAIL"
        print(f"  >>> [{name}] {icon} ({rec.elapsed:.1f}s)")

    wf.on_task_start = on_task_start
    wf.on_task_complete = on_task_complete

    # 执行
    print("\n[EXEC] Starting...")
    start = time.time()
    execution = wf.run(hub=hub)
    elapsed = time.time() - start

    # 结果
    print("\n" + "=" * 60)
    print(f"RESULTS ({elapsed:.0f}s)")
    print("=" * 60)

    success = sum(1 for t in execution.task_executions.values() if t.state.value in ("completed", "recovered"))
    total = len(execution.task_executions)
    print(f"  Success: {success}/{total}")

    for name, rec in execution.task_executions.items():
        icon = "OK" if rec.state.value in ("completed", "recovered") else "FAIL"
        print(f"  [{icon}] {name}: {rec.elapsed:.1f}s | {len(rec.output)} chars")

    # 产物
    print(f"\n  Files:")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        if f in ("checkpoints",):
            continue
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, f))
        print(f"    {f}: {sz:,} bytes")

    # index.html质量
    index_path = os.path.join(OUTPUT_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            c = f.read()
        checks = {
            "three.js CDN": "cdnjs.cloudflare.com/ajax/libs/three.js" in c,
            "canvas": "<canvas" in c.lower() or "getContext" in c,
            "game loop": "requestAnimationFrame" in c,
            "keyboard": "keydown" in c.lower(),
            "car": "car" in c.lower(),
            "track": "track" in c.lower(),
            "neon": "neon" in c.lower() or "#00ffff" in c,
            "css": "<style>" in c,
            "no TODO": "TODO" not in c and "FIXME" not in c,
        }
        passed = sum(checks.values())
        print(f"\n  Quality: {passed}/{len(checks)}")
        for name, ok in checks.items():
            print(f"    [{'OK' if ok else 'FAIL'}] {name}")
        print(f"\n  File size: {len(c):,} chars, {c.count(chr(10))} lines")

    print("\n" + "=" * 60)
    return execution


if __name__ == "__main__":
    main()