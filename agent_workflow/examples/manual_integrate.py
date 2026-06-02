from pathlib import Path
"""手动运行integrate来测试。"""
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import Agent, AgentConfig
from core.llm import DeepSeekLLM
from core.tool import tool

output_dir = str(Path(__file__).parent / 'output')

@tool
def save_file(filepath: str, content: str) -> str:
    import os
    full_path = os.path.join(output_dir, filepath)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Saved: {filepath} ({len(content)} chars)"

@tool
def read_file(filepath: str) -> str:
    import os
    full_path = os.path.join(output_dir, filepath)
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()

llm = DeepSeekLLM(api_key="sk-4af21c8a7b2a41dcae4481d22528dc42", model="deepseek-chat", timeout=300)
integrator = Agent(llm=llm, tools=[save_file, read_file], config=AgentConfig(max_iterations=20), name="integrator")

integrator.update_system_prompt(
    "You are an integration engineer. Read module files, combine into ONE index.html. "
    "Include Three.js CDN. Remove import/export. Make everything global. "
    "After saving, call done IMMEDIATELY."
)

result = integrator.run(
    "Step 1: Read core.js, track.js, car.js, ui.js\n"
    "Step 2: Combine into index.html with Three.js CDN\n"
    "Step 3: save_file('index.html', ...) then done()\n"
    "Be efficient. The game must run when opened."
)

print(f"Success: {result.success}")
print(f"Iterations: {result.iterations}")
print(f"Output: {result.output[:300]}")
