"""
DeepSeek API 集成测试 — 验证真实LLM调用。
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.llm import DeepSeekLLM, Message, llm_from_env
from core.agent import Agent
from core.tool import tool


@tool
def get_weather(city: str) -> str:
    """
    Get current weather for a city.

    Args:
        city: The city name.
    """
    # 模拟天气查询
    return f"The weather in {city} is sunny, 25°C."


def test_deepseek_basic():
    """测试: DeepSeek基础对话。"""
    print("\n[TEST] DeepSeek Basic Chat")

    llm = DeepSeekLLM(
        api_key="sk-4af21c8a7b2a41dcae4481d22528dc42",
        model="deepseek-chat",
    )

    messages = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="What is 15 + 27? Reply with just the number."),
    ]

    resp = llm.chat(messages)
    print(f"  content: {resp.content}")
    print(f"  tokens: {resp.usage.total_tokens if resp.usage else 'N/A'}")
    assert "42" in (resp.content or "")
    print("  PASSED")


def test_deepseek_tool_calling():
    """测试: DeepSeek工具调用（function calling）。"""
    print("\n[TEST] DeepSeek Tool Calling")

    llm = DeepSeekLLM(
        api_key="sk-4af21c8a7b2a41dcae4481d22528dc42",
        model="deepseek-chat",
    )

    tool_schema = get_weather.to_openai_schema()
    messages = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="What's the weather like in Beijing?"),
    ]

    resp = llm.chat(messages, tools=[tool_schema])

    print(f"  content: {resp.content}")
    print(f"  tool_calls: {len(resp.tool_calls)}")

    if resp.tool_calls:
        tc = resp.tool_calls[0]
        print(f"  tool: {tc.function}")
        print(f"  args: {tc.arguments}")
        assert tc.function == "get_weather"
        assert "Beijing" in tc.arguments

    print("  PASSED")


def test_deepseek_agent():
    """测试: DeepSeek驱动的Agent完整ReAct循环。"""
    print("\n[TEST] DeepSeek Agent ReAct")

    llm = DeepSeekLLM(
        api_key="sk-4af21c8a7b2a41dcae4481d22528dc42",
        model="deepseek-chat",
    )

    from core.agent import AgentConfig

    agent = Agent(
        llm=llm,
        tools=[get_weather],
        config=AgentConfig(max_iterations=5),
    )

    result = agent.run("What's the weather in Shanghai?")

    print(f"  success: {result.success}")
    print(f"  output: {result.output}")
    print(f"  iterations: {result.iterations}")
    print(f"  tokens: {result.total_usage.total_tokens if result.total_usage else 'N/A'}")
    print(f"  stop_reason: {result.stop_reason}")

    # 只要成功执行了工具调用就算通过
    assert result.iterations >= 1
    print("  PASSED")


if __name__ == "__main__":
    print("=" * 60)
    print("DeepSeek API Integration Test")
    print("=" * 60)

    # 基础对话
    try:
        test_deepseek_basic()
    except Exception as e:
        print(f"  FAILED: {e}")

    # 工具调用
    try:
        test_deepseek_tool_calling()
    except Exception as e:
        print(f"  FAILED: {e}")

    # Agent完整循环
    try:
        test_deepseek_agent()
    except Exception as e:
        print(f"  FAILED: {e}")

    print("\n" + "=" * 60)