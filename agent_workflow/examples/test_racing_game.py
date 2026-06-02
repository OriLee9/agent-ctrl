"""
端到端实战测试 — 使用框架开发HTML5赛车游戏。

测试目标:
1. Skill加载与Agent配置
2. WorkflowV2固定Task链执行
3. spawn_sub_agent子Agent调用
4. DeepSeek真实API调用
5. ContextHub上下文监控
6. 产物质量评估

Workflow设计:
    [设计] → [开发] → [审查]
    
    设计: game_designer Skill - 设计游戏机制、画面、操作
    开发: game_developer Skill - 编写完整可运行的HTML5赛车游戏
    审查: code_reviewer Skill - 审查代码、找bug、建议改进
"""
from __future__ import annotations

from pathlib import Path
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import Agent, AgentConfig
from core.llm import DeepSeekLLM, Message
from core.memory import Conversation
from core.skill import Skill, SkillRegistry
from core.sub_agent import SubAgentManager
from core.tool import tool
from orchestration.context_hub import ContextHub
from orchestration.task import Task
from orchestration.workflow_v2 import TaskNode, WorkflowV2


# ── 赛车游戏专用工具 ──────────────────────────────────────────

@tool
def save_file(filepath: str, content: str) -> str:
    """
    Save content to a file.
    
    Args:
        filepath: File path (relative to output directory)
        content: File content
    """
    import os
    output_dir = str(Path(__file__).parent / 'output')
    os.makedirs(output_dir, exist_ok=True)
    full_path = os.path.join(output_dir, filepath)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"File saved: {full_path} ({len(content)} chars)"


@tool
def read_file(filepath: str) -> str:
    """
    Read content from a file.
    
    Args:
        filepath: File path (relative to output directory)
    """
    import os
    output_dir = str(Path(__file__).parent / 'output')
    full_path = os.path.join(output_dir, filepath)
    if not os.path.exists(full_path):
        return f"[ERROR] File not found: {full_path}"
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


@tool
def file_exists(filepath: str) -> str:
    """
    Check if a file exists.
    
    Args:
        filepath: File path (relative to output directory)
    """
    import os
    output_dir = str(Path(__file__).parent / 'output')
    full_path = os.path.join(output_dir, filepath)
    return "true" if os.path.exists(full_path) else "false"


# ── 主测试函数 ────────────────────────────────────────────────

def test_framework_end_to_end():
    """端到端框架测试：开发赛车游戏。"""
    
    print("=" * 70)
    print("Agent Workflow Framework — End-to-End Test: Racing Game")
    print("=" * 70)
    
    # 1. 初始化LLM
    print("\n[1/6] Initializing DeepSeek LLM...")
    llm = DeepSeekLLM(
        api_key="sk-4af21c8a7b2a41dcae4481d22528dc42",
        model="deepseek-chat",
    )
    print(f"  LLM: {llm.model_id()}")
    
    # 2. 创建ContextHub
    print("\n[2/6] Setting up ContextHub...")
    hub = ContextHub()
    
    # 3. 注册Skills
    print("\n[3/6] Registering Skills...")
    registry = SkillRegistry()
    
    registry.register(Skill(
        name="game_designer",
        description="Game designer specializing in casual racing games",
        system_prompt=(
            "You are an expert game designer specializing in casual browser games. "
            "You design games that are fun, intuitive, and visually appealing. "
            "Your designs are practical and can be implemented by developers. "
            "Output your design as a structured document."
        ),
        tools=[save_file],
    ))
    
    registry.register(Skill(
        name="game_developer",
        description="Full-stack game developer for HTML5 Canvas games",
        system_prompt=(
            "You are an expert HTML5 game developer. You write clean, complete, "
            "self-contained code. All games use HTML5 Canvas and vanilla JavaScript. "
            "You always output complete, runnable files - never partial code or placeholders. "
            "Save all code files using the save_file tool. "
            "You can use spawn_sub_agent to delegate specialized sub-tasks."
        ),
        tools=[save_file, read_file, file_exists],
    ))
    
    registry.register(Skill(
        name="code_reviewer",
        description="Code reviewer for game projects",
        system_prompt=(
            "You are a meticulous code reviewer specializing in HTML5 games. "
            "You check for: bugs, performance issues, code quality, completeness, "
            "and playability. Provide specific, actionable feedback."
        ),
        tools=[read_file, file_exists],
    ))
    
    print(f"  Registered skills: {[s['name'] for s in registry.list_skills()]}")
    
    # 4. 创建Agents
    print("\n[4/6] Creating Agents with Skills...")
    
    designer = Agent(llm=llm, config=AgentConfig(max_iterations=5), name="designer")
    registry.apply_to_agent("game_designer", designer)
    
    developer = Agent(llm=llm, config=AgentConfig(max_iterations=10), name="developer")
    registry.apply_to_agent("game_developer", developer)
    
    reviewer = Agent(llm=llm, config=AgentConfig(max_iterations=5), name="reviewer")
    registry.apply_to_agent("code_reviewer", reviewer)
    
    # 为developer添加spawn_sub_agent工具
    sub_manager = SubAgentManager(developer, hub)
    developer.register_tool(sub_manager.create_tool())
    
    print(f"  Designer tools: {designer.list_tools()}")
    print(f"  Developer tools: {developer.list_tools()}")
    print(f"  Reviewer tools: {reviewer.list_tools()}")
    
    # 5. 构建WorkflowV2
    print("\n[5/6] Building WorkflowV2...")
    
    wf = WorkflowV2("racing_game_dev")
    wf.register_agent("designer", designer)
    wf.register_agent("developer", developer)
    wf.register_agent("reviewer", reviewer)
    wf.set_hub(hub)
    
    # Task 1: 游戏设计
    wf.add_task(TaskNode(
        task=Task(
            name="design",
            description=(
                "Design a complete casual racing game. Create a design document that includes:\n"
                "1. Game concept and core mechanics\n"
                "2. Screen layout and UI elements\n"
                "3. Player controls (keyboard)\n"
                "4. Game objects: player car, enemy cars, road, obstacles\n"
                "5. Scoring system and difficulty progression\n"
                "6. Visual style and colors\n"
                "Save the design document as 'design.md' using the save_file tool."
            ),
        ),
        agent_id="designer",
        description="Game design phase",
    ))
    
    # Task 2: 游戏开发
    wf.add_task(TaskNode(
        task=Task(
            name="develop",
            description=(
                "Create a complete, playable HTML5 racing game. Read the design from 'design.md' first, "
                "then implement the game as a single HTML file 'index.html' with embedded CSS and JavaScript.\n"
                "The game MUST include:\n"
                "- Canvas-based rendering\n"
                "- Player car controlled with arrow keys (left/right to steer, up to accelerate)\n"
                "- Enemy cars on the road to avoid\n"
                "- Collision detection\n"
                "- Score system\n"
                "- Game over and restart\n"
                "- Road scrolling effect\n"
                "Save the complete game as 'index.html' using the save_file tool.\n"
                "The game must be fully self-contained in a single HTML file."
            ),
        ),
        agent_id="developer",
        description="Game development phase",
    ))
    
    # Task 3: 代码审查
    wf.add_task(TaskNode(
        task=Task(
            name="review",
            description=(
                "Review the racing game code in 'index.html'. Check for:\n"
                "1. Does the game run without errors?\n"
                "2. Is the gameplay fun and responsive?\n"
                "3. Are there any bugs or issues?\n"
                "4. Is the code well-structured?\n"
                "5. Suggest specific improvements.\n"
                "Provide a detailed review report."
            ),
        ),
        agent_id="reviewer",
        description="Code review phase",
    ))
    
    print(f"  Tasks: {[t['name'] for t in wf.list_tasks()]}")
    
    # 6. 执行Workflow
    print("\n[6/6] Executing Workflow...")
    print("  " + "-" * 66)
    
    start_time = time.time()
    
    # 设置钩子监控执行
    def on_task_start(name: str, node: TaskNode):
        print(f"\n  >>> Task START: {name} (agent: {node.agent_id})")
    
    def on_task_complete(name: str, exec_record):
        status = "OK" if exec_record.state.value == "completed" else "FAIL"
        print(f"  >>> Task END: {name} [{status}] output_len={len(exec_record.output)}")
    
    wf.on_task_start = on_task_start
    wf.on_task_complete = on_task_complete
    
    execution = wf.run(hub=hub)
    
    elapsed = time.time() - start_time
    
    # ── 结果汇总 ────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    print(f"\nWorkflow State: {execution.state.value}")
    print(f"Total Time: {elapsed:.1f}s")
    print(f"Tasks Executed: {len(execution.task_executions)}")
    
    for name, exec_rec in execution.task_executions.items():
        print(f"\n  [{name}] state={exec_rec.state.value} time={exec_rec.elapsed:.1f}s")
        print(f"  Output (first 300 chars):")
        print(f"  {exec_rec.output[:300]}...")
    
    # ContextHub统计
    print(f"\nContextHub Agents: {hub.list_agents()}")
    for aid in hub.list_agents():
        summary = hub.agent_summary(aid)
        if summary:
            print(f"  {aid}: {summary['message_count']} msgs, {summary['step_count']} steps, {summary['total_usage']['total_tokens']} tokens")
    
    # 检查产物
    print("\n" + "-" * 70)
    print("OUTPUT FILES:")
    import os
    output_dir = str(Path(__file__).parent / 'output')
    if os.path.exists(output_dir):
        for f in sorted(os.listdir(output_dir)):
            fpath = os.path.join(output_dir, f)
            size = os.path.getsize(fpath)
            print(f"  {f}: {size} bytes")
    else:
        print("  No output directory found!")
    
    # 检查index.html是否可以运行
    index_path = os.path.join(output_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            content = f.read()
        has_canvas = "<canvas" in content.lower() or "canvas" in content.lower()
        has_js = "<script" in content.lower()
        has_game_loop = "requestanimationframe" in content.lower() or "setinterval" in content.lower()
        
        print(f"\nGame Quality Check:")
        print(f"  Has Canvas: {has_canvas}")
        print(f"  Has JavaScript: {has_js}")
        print(f"  Has Game Loop: {has_game_loop}")
        print(f"  File Size: {len(content)} chars")
    
    print("\n" + "=" * 70)
    
    return execution


if __name__ == "__main__":
    try:
        test_framework_end_to_end()
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)