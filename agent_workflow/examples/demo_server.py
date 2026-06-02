"""
演示服务器 — 启动Flask API + 模拟Agent运行产生实时事件。

用法:
    python demo_server.py

然后访问 http://localhost:5000 查看监控面板。
"""
from __future__ import annotations

from pathlib import Path
import json
import random
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import Agent, AgentConfig
from core.llm import BaseLLM, LLMResponse, Message, ToolCall, Usage
from core.tool import tool
from orchestration.context_hub import ContextHub, Intervention
from orchestration.rules import RuleConfig, SimpleRuleEngine
from orchestration.task import Task
from orchestration.workflow import Workflow


# ── Mock LLM ───────────────────────────────────────────────────

class DemoLLM(BaseLLM):
    """演示用的Mock LLM，模拟多步推理。"""

    def __init__(self, name: str = "demo"):
        self.name = name
        self.call_count = 0
        self._responses: list[LLMResponse] = []
        self._setup_responses()

    def _setup_responses(self) -> None:
        """预设响应序列（多步ReAct）。"""
        # 场景: 研究任务 — 搜索→总结→完成
        self._responses = [
            LLMResponse(
                content="I need to search for information about AI agents.",
                tool_calls=[ToolCall(id="c1", function="search", arguments='{"query": "AI agent frameworks 2024"}')],
                usage=Usage(15, 20, 35),
            ),
            LLMResponse(
                content="Now let me analyze the search results.",
                tool_calls=[ToolCall(id="c2", function="analyze", arguments='{"data": "AI agent frameworks"}')],
                usage=Usage(12, 18, 30),
            ),
            LLMResponse(
                content="I have completed the analysis.",
                tool_calls=[ToolCall(id="c3", function="done", arguments='{"result": "Found 3 major frameworks: LangChain, AutoGen, and CrewAI. Each has different strengths."}')],
                usage=Usage(10, 15, 25),
            ),
        ]

    def model_id(self) -> str:
        return f"mock:{self.name}"

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        self.call_count += 1
        if self.call_count <= len(self._responses):
            return self._responses[self.call_count - 1]
        # 默认完成
        return LLMResponse(
            content="Done.",
            tool_calls=[ToolCall(id="cf", function="done", arguments='{"result": "Task completed."}')],
            usage=Usage(5, 5, 10),
        )


# ── 演示工具 ───────────────────────────────────────────────────

@tool
def search(query: str) -> str:
    """Search the knowledge base."""
    results = {
        "AI agent frameworks 2024": "1. LangChain - modular, popular\n2. AutoGen - Microsoft, multi-agent\n3. CrewAI - role-based, simple",
        "machine learning": "ML is a subset of AI focused on learning from data.",
    }
    return results.get(query, f"Found 5 results for '{query}'")


@tool
def analyze(data: str) -> str:
    """Analyze data and provide insights."""
    return f"Analysis of '{data}': Key trends show increasing adoption of multi-agent systems."


# ── 演示场景 ───────────────────────────────────────────────────

class DemoScenario:
    """演示场景管理器。"""

    def __init__(self):
        self.hub = ContextHub()
        self.rule_engine: SimpleRuleEngine | None = None
        self.agents: dict[str, Agent] = {}
        self._stop_event = threading.Event()

    def setup(self) -> None:
        """初始化演示场景。"""
        # 创建Agent
        for name in ["researcher", "writer", "reviewer"]:
            llm = DemoLLM(name)
            agent = Agent(
                llm=llm,
                tools=[search, analyze],
                config=AgentConfig(max_iterations=5),
                name=name,
            )
            self.agents[name] = agent
            self.hub.register(name, f"You are the {name} agent.")

        # 启动规则引擎
        self.rule_engine = SimpleRuleEngine(self.hub, RuleConfig(
            max_repeated_short_thoughts=3,
            short_thought_threshold=15,
        ))
        self.rule_engine.start()

        print(f"[Demo] Created {len(self.agents)} agents: {list(self.agents.keys())}")

    def run_scenario(self) -> None:
        """在后台线程运行演示场景。"""
        def _run():
            time.sleep(1)  # 等Flask启动

            # 给每个Agent分配任务
            tasks = {
                "researcher": "Research AI agent frameworks",
                "writer": "Write a summary about AI agents",
            }

            for agent_id, task in tasks.items():
                if self._stop_event.is_set():
                    break
                conv = self.hub.get(agent_id)
                if conv:
                    conv.add_user(task)
                    print(f"[Demo] Assigned task to {agent_id}: {task}")
                time.sleep(0.5)

            # 模拟agent间消息
            time.sleep(2)
            if not self._stop_event.is_set():
                self.hub.send_to_agent("researcher", "writer", "Here are my findings: LangChain, AutoGen, CrewAI are the top 3.")
                print("[Demo] Sent agent-to-agent message")

            # 模拟短句重复（触发规则引擎）
            time.sleep(3)
            if not self._stop_event.is_set():
                conv = self.hub.get("reviewer")
                if conv:
                    for thought in ["Hmm...", "Wait...", "Let me check..."]:
                        conv.record_step(__import__('core.memory', fromlist=['StepRecord']).StepRecord(thought=thought))
                    print("[Demo] Triggered repeated short thoughts rule")

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def stop(self) -> None:
        self._stop_event.set()


# ── 主入口 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Agent Workflow Monitor — Demo Server")
    print("=" * 60)

    # 创建演示场景
    scenario = DemoScenario()
    scenario.setup()

    # 注入hub到Flask app
    from api_server import app, hub as server_hub, rule_engine as server_rule_engine

    # 替换Flask的全局hub为我们的演示hub
    import api_server
    api_server.hub = scenario.hub

    print("\n[Demo] Starting Flask server...")
    print("Open http://localhost:5000 in your browser")
    print("Press Ctrl+C to stop\n")

    # 启动演示场景
    scenario.run_scenario()

    # 启动Flask
    try:
        from werkzeug.serving import make_server
        server = make_server('0.0.0.0', 5000, app, threaded=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Demo] Shutting down...")
        scenario.stop()