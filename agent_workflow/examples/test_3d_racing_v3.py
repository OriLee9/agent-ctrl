"""
3D赛车游戏测试 v3 — 断点续跑 + Task级超时 + 保证每个环节成功。

保证成功的策略:
1. 每个Task独立Conversation + 产物传递
2. Task级超时: integrate 300s(超大), 其他默认120s
3. 自动重试: 失败自动重试2次
4. 断点续跑: 失败后保存checkpoint, resume()继续
5. 最终保险: 如果API实在无法整合, 用本地脚本fallback整合
"""
from __future__ import annotations

from pathlib import Path
import os
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
        return f"[ERROR] File not found: {filepath}"
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


@tool
def file_exists(filepath: str) -> str:
    full_path = os.path.join(OUTPUT_DIR, filepath)
    return "true" if os.path.exists(full_path) else "false"


def print_banner(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def fallback_integrate() -> bool:
    """当API整合失败时的fallback: 本地脚本整合。"""
    import re

    print("\n  [FALLBACK] Running local integration script...")

    def clean_js(code):
        code = re.sub(r'^\s*import\s+.*?;?\s*$', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*export\s+.*?;?\s*$', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*export\s+default\s+.*?;?\s*$', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*export\s*\{[^}]*\}\s*;?\s*$', '', code, flags=re.MULTILINE)
        return code

    modules = {}
    for fname in ["core.js", "track.js", "car.js", "ui.js"]:
        fpath = os.path.join(OUTPUT_DIR, fname)
        if not os.path.exists(fpath):
            print(f"    ERROR: Missing {fname}")
            return False
        with open(fpath, "r") as f:
            modules[fname.replace(".js", "")] = clean_js(f.read())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Neon Drift — 3D Racing</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #0a0a1a; overflow: hidden; font-family: 'Segoe UI', Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; }}
#gameContainer {{ position: relative; width: 100vw; height: 100vh; }}
#gameContainer canvas {{ display: block; width: 100%; height: 100%; }}
</style>
</head>
<body>
<div id="gameContainer"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
// ============================================================
// Neon Drift — 3D Racing Game (auto-integrated)
// ============================================================
{modules.get("core", "// core missing")}
{modules.get("track", "// track missing")}
{modules.get("car", "// car missing")}
{modules.get("ui", "// ui missing")}
// Auto-init
try {{ if(typeof initEngine==='function') initEngine('gameContainer'); }} catch(e) {{ console.error('initEngine:', e); }}
try {{ if(typeof initUI==='function') initUI(); }} catch(e) {{ console.error('initUI:', e); }}
console.log('Neon Drift loaded');
</script>
</body>
</html>"""

    with open(os.path.join(OUTPUT_DIR, "index.html"), "w") as f:
        f.write(html)

    print(f"    index.html created: {len(html):,} chars")
    return True


def main():
    print_banner("3D Racing Game v3 — Checkpoint Resume + Task Timeout")

    # 初始化
    llm = DeepSeekLLM(api_key="sk-4af21c8a7b2a41dcae4481d22528dc42", model="deepseek-chat", timeout=120)
    hub = ContextHub()
    registry = SkillRegistry()

    # 注册Skills
    registry.register(Skill(
        name="game_designer",
        description="Game designer",
        system_prompt="You are an expert game designer. Create detailed design docs. After saving, IMMEDIATELY call done().",
        tools=[save_file],
    ))
    registry.register(Skill(
        name="engine_dev",
        description="Three.js developer",
        system_prompt=(
            "You are a Three.js expert. CRITICAL: Do NOT read previous files. "
            "Create standalone module. Export as window.xxx globals. "
            "After saving, IMMEDIATELY call done(result='saved')."
        ),
        tools=[save_file, file_exists],
    ))
    registry.register(Skill(
        name="car_dev",
        description="Car physics developer",
        system_prompt=(
            "You are a vehicle physics expert. CRITICAL: Do NOT read previous files. "
            "Create standalone car.js. Export window.Car class. "
            "Car.update(input, dt), Car.getPosition(). "
            "After saving, IMMEDIATELY call done(result='saved')."
        ),
        tools=[save_file, file_exists],
    ))
    registry.register(Skill(
        name="ui_dev",
        description="UI developer",
        system_prompt=(
            "You are a game UI expert. CRITICAL: Do NOT read previous files. "
            "Create standalone ui.js. Export window.initUI, window.showScreen. "
            "After saving, IMMEDIATELY call done(result='saved')."
        ),
        tools=[save_file, file_exists],
    ))
    registry.register(Skill(
        name="integrator",
        description="Integration engineer",
        system_prompt=(
            "You are an integration engineer. Read ALL 4 .js files. "
            "Combine into ONE index.html. Remove import/export. Make everything global. "
            "Include Three.js CDN. After saving, IMMEDIATELY call done()."
        ),
        tools=[save_file, read_file],
    ))

    # 创建Agents
    agents_config = {"max_iterations": 15}
    designer = Agent(llm=llm, tools=[save_file], config=AgentConfig(**agents_config), name="designer")
    registry.apply_to_agent("game_designer", designer)

    engine_dev = Agent(llm=llm, tools=[save_file, file_exists], config=AgentConfig(**agents_config), name="engine_dev")
    registry.apply_to_agent("engine_dev", engine_dev)
    engine_dev.register_tool(SubAgentManager(engine_dev, hub).create_tool())

    car_dev = Agent(llm=llm, tools=[save_file, file_exists], config=AgentConfig(**agents_config), name="car_dev")
    registry.apply_to_agent("car_dev", car_dev)

    ui_dev = Agent(llm=llm, tools=[save_file, file_exists], config=AgentConfig(**agents_config), name="ui_dev")
    registry.apply_to_agent("ui_dev", ui_dev)

    # Integrator使用更长超时
    llm_long = DeepSeekLLM(api_key="sk-4af21c8a7b2a41dcae4481d22528dc42", model="deepseek-chat", timeout=300)
    integrator = Agent(llm=llm_long, tools=[save_file, read_file], config=AgentConfig(**agents_config), name="integrator")
    registry.apply_to_agent("integrator", integrator)

    # 构建Workflow
    wf = WorkflowV2("3d_racing_v3", checkpoint_dir=os.path.join(OUTPUT_DIR, "checkpoints"))
    wf.register_agent("designer", designer)
    wf.register_agent("engine_dev", engine_dev)
    wf.register_agent("car_dev", car_dev)
    wf.register_agent("ui_dev", ui_dev)
    wf.register_agent("integrator", integrator)
    wf.set_hub(hub)

    # 添加Tasks(关键: integrate配置300s超时和2次重试)
    wf.add_task(TaskNode(Task(name="design", description="Create 'design.md' — comprehensive 3D racing game design with neon aesthetic, Three.js approach, controls, scoring. Save then done."), agent_id="designer"))
    wf.add_task(TaskNode(Task(name="develop_core", description="Create 'core.js' — Three.js engine: initEngine(), scene, camera(fov75), renderer, gameLoop with rAF, dark bg #0a0a1a. Export as globals. Save then done."), agent_id="engine_dev"))
    wf.add_task(TaskNode(Task(name="develop_track", description="Create 'track.js' — procedural infinite track with curves, neon environment (cyan #00ffff, magenta #ff00ff), glowing pillars. Export as globals. Save then done."), agent_id="engine_dev"))
    wf.add_task(TaskNode(Task(name="develop_car", description="Create 'car.js' — Car class with physics (acceleration, drift, maxSpeed), neon materials, update(input,dt), getPosition(). Export window.Car. Save then done."), agent_id="car_dev"))
    wf.add_task(TaskNode(Task(name="develop_ui", description="Create 'ui.js' — initUI(), showScreen(start|game|gameover), HUD (speedometer, timer, score), neon CSS text-shadow. Export globals. Save then done."), agent_id="ui_dev"))
    wf.add_task(TaskNode(
        Task(name="integrate", description="Read core.js, track.js, car.js, ui.js. Combine into ONE index.html with Three.js CDN. Remove import/export. Make global. Save then done."),
        agent_id="integrator",
        timeout=300,  # 特殊: 300秒超时
        max_retries=2,  # 失败重试2次
    ))

    # 设置监控钩子
    def on_task_start(name, node):
        print(f"\n  >>> [{name}] START (agent={node.agent_id}, timeout={node.timeout or 'default'}, retries={node.max_retries})")

    def on_task_complete(name, exec_record):
        icon = "OK" if exec_record.state.value in ("completed", "recovered") else "FAIL"
        print(f"  >>> [{name}] {icon} ({exec_record.elapsed:.1f}s, {exec_record.retry_count} retries)")

    def on_recovery_needed(task_name, error, checkpoint):
        print(f"\n  !!! RECOVERY NEEDED: [{task_name}] failed: {error[:80]}")
        print(f"  Checkpoint: {wf.get_checkpoint_path()}")

    wf.on_task_start = on_task_start
    wf.on_task_complete = on_task_complete
    wf.on_recovery_needed = on_recovery_needed

    # 执行
    print("\n[EXEC] Starting Workflow...")
    start = time.time()
    execution = wf.run(hub=hub)

    # 如果integrate失败, 使用fallback
    if execution.state == WorkflowState.WAITING_RECOVERY:
        failed_task = execution.current_task
        print(f"\n  Workflow paused at [{failed_task}]. Attempting recovery...")

        if failed_task == "integrate":
            # Fallback: 本地整合
            if fallback_integrate():
                print("  Fallback integration succeeded. Resuming workflow...")
                wf.resume_from_recovery()
                # 等待workflow完成
                time.sleep(2)
            else:
                print("  Fallback also failed.")

    elapsed = time.time() - start

    # 结果汇总
    print_banner(f"RESULTS ({elapsed:.0f}s)")

    success_count = sum(1 for t in execution.task_executions.values()
                        if t.state.value in ("completed", "recovered"))
    print(f"  Success: {success_count}/{len(execution.task_executions)}")

    for name, rec in execution.task_executions.items():
        icon = "OK" if rec.state.value in ("completed", "recovered") else "FAIL"
        print(f"  [{icon}] {name}: {rec.elapsed:.1f}s | {len(rec.output)} chars | retries={rec.retry_count}")

    # 产物检查
    print(f"\n  Output Files:")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        if f.endswith(".log") or f == "checkpoints":
            continue
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, f))
        print(f"    {f}: {sz:,} bytes")

    # index.html质量检查
    index_path = os.path.join(OUTPUT_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            content = f.read()
        checks = {
            "three.js": "three" in content.lower() or "THREE" in content,
            "canvas": "<canvas" in content.lower() or "getContext" in content,
            "game loop": "requestAnimationFrame" in content,
            "keyboard": "keydown" in content.lower(),
            "car": "car" in content.lower(),
            "track/road": "track" in content.lower() or "road" in content.lower(),
            "neon style": "neon" in content.lower() or "#00ffff" in content,
            "no TODO": "TODO" not in content and "FIXME" not in content,
        }
        print(f"\n  Quality Check ({sum(checks.values())}/{len(checks)}):")
        for check, passed in checks.items():
            print(f"    [{'PASS' if passed else 'FAIL'}] {check}")

    print_banner("COMPLETE")
    return execution


if __name__ == "__main__":
    main()