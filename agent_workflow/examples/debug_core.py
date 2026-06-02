from pathlib import Path
"""Debug: test single develop_core with stronger prompt."""
import sys
import os
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import Agent, AgentConfig
from core.llm import DeepSeekLLM
from core.tool import tool

output_dir = str(Path(__file__).parent / 'output')
os.makedirs(output_dir, exist_ok=True)

@tool
def save_file_s(filepath: str, content: str) -> str:
    full_path = os.path.join(output_dir, filepath)
    with open(full_path, 'w') as f:
        f.write(content)
    return f"Saved: {filepath} ({len(content)} chars, {content.count(chr(10))} lines)"

llm = DeepSeekLLM(api_key='sk-4af21c8a7b2a41dcae4481d22528dc42', model='deepseek-chat', timeout=120)
agent = Agent(llm=llm, tools=[save_file_s], config=AgentConfig(max_iterations=20), name='engine_dev')
agent.update_system_prompt(
    "You are a Three.js expert. Write COMPLETE production code. "
    "MANDATORY: Your code must be at least 500 lines. "
    "Every function fully implemented with REAL logic, NOT placeholder comments. "
    "Export as window.xxx globals. "
    "After save_file(), call done(result='saved N lines')."
)

result = agent.run(
    "Create 'core.js' — Three.js engine module. MUST be at least 500 lines. "
    "initEngine(containerId): creates scene, PerspectiveCamera(fov75), WebGLRenderer, "
    "requestAnimationFrame game loop with delta time, dark bg #0a0a1a with fog, resize handler. "
    "Export window.initEngine. "
    "Write FULL code with REAL implementation. Call save_file then done."
)
print(f"Success: {result.success}")
print(f"Iterations: {result.iterations}")
print(f"Stop reason: {result.stop_reason}")
print(f"Output: {result.output}")

# Check file
if os.path.exists(os.path.join(output_dir, 'core.js')):
    with open(os.path.join(output_dir, 'core.js')) as f:
        content = f.read()
    print(f"\nFile size: {len(content)} chars, {content.count(chr(10))} lines")
    print(f"First 200 chars: {content[:200]}")
