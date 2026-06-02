"""
自主3D赛车游戏 — Agent自主规划，不预设固定Workflow。

测试目标:
1. Agent自主规划能力（无预设Task链）
2. FileContextManager在长任务中的实际表现
3. 框架在开放性问题上的端到端验证
4. 使用DeepSeek-v4-pro生成高质量代码

策略:
- 一个强力Agent，配备完整的文件操作工具
- Agent自主决定：先设计→再编码→再集成→最后部署
- ContextHub全程监控，记录每个决策点
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import Agent, AgentConfig
from core.file_context import FileContextManager
from core.file_tools import FileTools
from core.llm import DeepSeekLLM
from core.tool import done, tool
from orchestration.context_hub import ContextHub


# ── 项目目录 ──────────────────────────────────────────────────

PROJECT_DIR = str(Path(__file__).parent / 'output')
os.makedirs(PROJECT_DIR, exist_ok=True)

# ── 系统提示词 ────────────────────────────────────────────────

RACING_ARCHITECT_SYSTEM = """You are an expert 3D game architect specializing in Three.js and WebGL.

Your task is to create a complete, beautiful 3D racing game as a single HTML file.

GAME REQUIREMENTS:
- Stunning 3D racing game using Three.js (via CDN: https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js)
- Immersive gameplay with proper vehicle physics (acceleration, braking, drifting, collision)
- Beautiful 3D environment: terrain, skybox, lighting, particle effects
- Multiple camera modes (chase cam, cockpit cam, overhead)
- Scoring system with lap times and best records
- Beautiful UI overlay (speedometer, minimap, lap counter, timer)
- Sound effects (engine rev, collision, skidding)
- Day/night cycle or at least dynamic lighting
- Road/track with curbs, barriers, and environment decorations (trees, buildings, rocks)
- Responsive controls (keyboard + optional touch)
- Title screen with game start flow

CRITICAL RULES:
1. The game MUST be a single self-contained index.html file
2. Use Three.js r128 from CDN - NO module imports, NO build step
3. All code in ONE file: <script> tags with inline JavaScript
4. NO placeholder functions - every function must have real implementation
5. The game must be PLAYABLE when opened in a browser
6. Target 60fps on modern hardware
7. Code quality: clean, well-commented, professional game development patterns

THINK STEP BY STEP. Plan the architecture before coding.
Consider:
- Game loop structure (update + render)
- Physics simulation (vehicle dynamics, collision detection)
- Track generation (procedural or predefined waypoints)
- Rendering pipeline (shadows, post-processing if possible)
- State management (menu, racing, paused, game over)
- Asset creation (procedural textures, geometry)

Write the COMPLETE game. Do NOT skip any feature.
"""

# ── 工具 ──────────────────────────────────────────────────────

@tool
def write_file(path: str, content: str) -> str:
    """
    Write content to a file in the project directory.
    
    Args:
        path: Relative path within project (e.g., "index.html", "js/game.js")
        content: File content
    """
    full = os.path.join(PROJECT_DIR, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    size = os.path.getsize(full)
    return f"Written {path}: {size:,} bytes"


@tool
def read_file(path: str) -> str:
    """Read a file from the project directory."""
    full = os.path.join(PROJECT_DIR, path)
    if not os.path.exists(full):
        return f"[File not found: {path}]"
    with open(full, "r", encoding="utf-8") as f:
        return f.read()


@tool  
def list_project_files() -> str:
    """List all files in the project directory."""
    files = []
    for dirpath, dirnames, filenames in os.walk(PROJECT_DIR):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, PROJECT_DIR)
            size = os.path.getsize(fp)
            files.append(f"  {rel}: {size:,} bytes")
    return "\n".join(files) if files else "  (empty)"


# ── 主流程 ────────────────────────────────────────────────────

def run_autonomous_game():
    print("=" * 70)
    print("Autonomous 3D Racing Game — Agent-driven development")
    print("=" * 70)
    print(f"Project dir: {PROJECT_DIR}")
    print(f"API Key: {'*' * 20}{os.environ.get('DEEPSEEK_API_KEY', 'NOT SET')[-8:]}")
    
    # 1. 设置 LLM 和 Agent
    llm = DeepSeekLLM(
        api_key="sk-4af21c8a7b2a41dcae4481d22528dc42",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        timeout=600,
    )
    
    hub = ContextHub(db_path = str(Path(tempfile.gettempdir()) / 'agent_workflow'))
    
    agent = Agent(
        llm=llm,
        tools=[done, write_file, read_file, list_project_files],
        config=AgentConfig(
            max_iterations=50,
            temperature=0.7,
            budget_tokens=500000,  # 500K token budget
            checkpoint_enabled=True,
            checkpoint_dir = str(Path(tempfile.gettempdir()) / 'agent_workflow'),
        ),
        name="racing_architect",
        system_prompt=RACING_ARCHITECT_SYSTEM,
    )
    
    # 2. 构建 Task prompt — 给Agent充分的自主性
    task = f"""Create a stunning 3D racing game. The game must be a single playable index.html file.

Project directory: {PROJECT_DIR}

YOUR WORKFLOW (you decide the order and approach):
1. Design the game architecture and plan
2. Create the index.html file with complete game implementation
3. Verify the file is complete and playable

AVAILABLE TOOLS:
- write_file(path, content): Write files to the project
- read_file(path): Read existing files
- list_project_files(): List all project files and sizes
- done(result): Call when finished

The game should include:
- Three.js 3D rendering (from CDN)
- Realistic car physics and controls
- Beautiful race track with environment
- Skybox, lighting, shadows
- Speedometer and HUD
- Lap timing and scoring
- Particle effects (dust, sparks)
- Multiple camera views
- Engine sounds using Web Audio API
- Title screen and game flow
- Mobile touch controls support

IMPORTANT: Write the COMPLETE game in a SINGLE index.html file.
Do NOT use external files - everything inline.
Make it visually stunning with modern 3D graphics techniques.

Begin by planning, then write the complete game."""

    # 3. 运行 Agent
    print("\n[Agent] Starting autonomous development...")
    print("-" * 70)
    
    start = time.time()
    
    # 流式输出
    def on_token(token: str):
        print(token, end="", flush=True)
    
    agent.on_stream = on_token
    
    # 状态钩子
    def on_step(step):
        pass  # 静默
    
    agent.on_step = on_step
    
    result = agent.run(task)
    
    elapsed = time.time() - start
    
    # 4. 结果报告
    print("\n" + "=" * 70)
    print("RESULT")
    print("=" * 70)
    print(f"Success: {result.success}")
    print(f"Iterations: {result.iterations}")
    print(f"Time: {elapsed:.1f}s")
    if result.total_usage:
        print(f"Tokens: {result.total_usage.total_usage:,}")
    print(f"Stop reason: {result.stop_reason}")
    
    # 文件列表
    print(f"\nFiles:")
    for item in list_project_files().split("\n"):
        print(f"  {item}")
    
    # 检查 index.html
    index_path = os.path.join(PROJECT_DIR, "index.html")
    if os.path.exists(index_path):
        size = os.path.getsize(index_path)
        print(f"\nindex.html: {size:,} bytes ({size/1024:.1f} KB)")
        
        with open(index_path, "r") as f:
            content = f.read()
        
        # 质量检查
        checks = {
            "Three.js CDN": "three.js" in content or "THREE" in content,
            "Game loop": "requestAnimationFrame" in content,
            "Keyboard controls": "keydown" in content or "Key" in content,
            "Car/vehicle": "car" in content.lower() or "vehicle" in content.lower(),
            "Camera": "Camera" in content or "camera" in content,
            "Physics": "velocity" in content or "physics" in content.lower(),
            "Collision": "collision" in content.lower() or "intersect" in content.lower(),
            "Track/Road": "track" in content.lower() or "road" in content.lower(),
            "HUD/UI": "hud" in content.lower() or "innerHTML" in content or "getElementById" in content,
            "Score/Timer": "score" in content.lower() or "time" in content.lower() or "lap" in content.lower(),
            "Sound": "Audio" in content or "sound" in content.lower(),
            "Skybox/Environment": "sky" in content.lower() or "fog" in content.lower() or "environment" in content.lower(),
        }
        
        print(f"\nQuality checks:")
        passed = 0
        for name, ok in checks.items():
            status = "OK" if ok else "MISSING"
            if ok:
                passed += 1
            print(f"  [{status}] {name}")
        print(f"\nScore: {passed}/{len(checks)} ({passed/len(checks)*100:.0f}%)")
    else:
        print(f"\nERROR: index.html not created!")
        print(f"Agent output:\n{result.output[:2000]}")

    # ContextHub 统计
    stats = hub.get_event_stats()
    print(f"\nContextHub events: {stats['total_events']}")
    
    return result


if __name__ == "__main__":
    run_autonomous_game()