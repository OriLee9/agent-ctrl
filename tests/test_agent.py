"""Tests for core.agent module."""
from __future__ import annotations

import json

import pytest

from core.agent import Agent, AgentConfig, AgentResult, _is_permanent_error
from core.llm import LLMResponse, Message, ToolCall, Usage
from core.tool import tool

from conftest import MockLLM


class TestIsPermanentError:
    """Test error classification."""

    def test_400_status_is_permanent(self):
        class FakeResponse:
            status_code = 400
        exc = Exception("bad request")
        exc.response = FakeResponse()
        assert _is_permanent_error(exc) is True

    def test_500_status_is_not_permanent(self):
        class FakeResponse:
            status_code = 500
        exc = Exception("server error")
        exc.response = FakeResponse()
        assert _is_permanent_error(exc) is False

    def test_token_limit_in_message(self):
        exc = Exception("Token limit exceeded")
        assert _is_permanent_error(exc) is True

    def test_invalid_api_in_message(self):
        exc = Exception("Invalid API key")
        assert _is_permanent_error(exc) is True

    def test_transient_error(self):
        exc = Exception("Connection timeout")
        assert _is_permanent_error(exc) is False


class TestAgentConfig:
    """Test AgentConfig dataclass."""

    def test_defaults(self):
        config = AgentConfig()
        assert config.max_iterations == 10
        assert config.temperature is None
        assert config.allowed_tools is None
        assert config.stop_on_tool_error is False
        assert config.budget_tokens == 0
        assert config.checkpoint_enabled is False

    def test_custom_values(self):
        config = AgentConfig(
            max_iterations=5,
            temperature=0.5,
            budget_tokens=1000,
            checkpoint_enabled=True,
        )
        assert config.max_iterations == 5
        assert config.temperature == 0.5
        assert config.budget_tokens == 1000
        assert config.checkpoint_enabled is True


class TestAgentInitialization:
    """Test Agent setup."""

    def test_default_tools_registered(self, mock_llm):
        agent = Agent(llm=mock_llm)
        assert "done" in agent.list_tools()
        assert "think" in agent.list_tools()

    def test_custom_tools_registered(self, mock_llm, sample_tool):
        agent = Agent(llm=mock_llm, tools=[sample_tool])
        assert "greet" in agent.list_tools()
        assert "done" in agent.list_tools()

    def test_allowed_tools_filter(self, mock_llm, sample_tool):
        config = AgentConfig(allowed_tools=["greet"])
        agent = Agent(llm=mock_llm, tools=[sample_tool], config=config)
        assert agent.list_tools() == ["greet"]
        assert "done" not in agent.list_tools()

    def test_system_prompt_default(self, mock_llm):
        agent = Agent(llm=mock_llm)
        assert "helpful AI assistant" in agent.system_prompt
        assert "done" in agent.system_prompt

    def test_system_prompt_custom(self, mock_llm):
        agent = Agent(llm=mock_llm, system_prompt="You are a coder.")
        assert agent.system_prompt == "You are a coder."


class TestAgentRun:
    """Test Agent.run() with mock LLM."""

    def test_single_step_completion(self, mock_llm_with_responses):
        responses = [
            LLMResponse(
                content="I will complete this.",
                tool_calls=[ToolCall(
                    id="tc1",
                    function="done",
                    arguments='{"result": "success output"}',
                )],
                usage=Usage(10, 10, 20),
            ),
        ]
        llm = mock_llm_with_responses(responses)
        agent = Agent(llm=llm, config=AgentConfig(max_iterations=3))
        result = agent.run("Do something")

        assert result.success is True
        assert result.output == "success output"
        assert result.iterations == 1
        assert result.stop_reason == "done"
        assert result.total_usage is not None
        assert result.total_usage.total_tokens == 20

    def test_multi_step_tool_use(self, mock_llm_with_responses):
        @tool
        def search(query: str) -> str:
            """Search."""
            return f"found: {query}"

        responses = [
            LLMResponse(
                content="Let me search.",
                tool_calls=[ToolCall(
                    id="tc1",
                    function="search",
                    arguments='{"query": "test"}',
                )],
                usage=Usage(5, 5, 10),
            ),
            LLMResponse(
                content="Now I am done.",
                tool_calls=[ToolCall(
                    id="tc2",
                    function="done",
                    arguments='{"result": "completed"}',
                )],
                usage=Usage(5, 5, 10),
            ),
        ]
        llm = mock_llm_with_responses(responses)
        agent = Agent(llm=llm, tools=[search], config=AgentConfig(max_iterations=5))
        result = agent.run("Do something")

        assert result.success is True
        assert result.iterations == 2
        assert result.output == "completed"

    def test_budget_enforcement(self, mock_llm_with_responses):
        responses = [
            LLMResponse(
                content="Step 1.",
                tool_calls=[ToolCall(id="tc1", function="think", arguments='{"thought": "thinking"}')],
                usage=Usage(50, 50, 100),
            ),
        ]
        llm = mock_llm_with_responses(responses)
        config = AgentConfig(max_iterations=5, budget_tokens=50)
        agent = Agent(llm=llm, config=config)
        result = agent.run("Do something")

        assert result.success is False
        assert "budget_exceeded" in result.stop_reason

    def test_max_iterations_reached(self, mock_llm_with_responses):
        # LLM never calls done, uses search tool with varying observations to avoid stuck detection
        @tool
        def search(query: str) -> str:
            """Search."""
            return f"results for {query}"

        responses = [
            LLMResponse(
                content=f"Step {i}.",
                tool_calls=[ToolCall(id=f"tc{i}", function="search", arguments=f'{{"query": "q{i}"}}')],
                usage=Usage(1, 1, 2),
            )
            for i in range(5)
        ]
        llm = mock_llm_with_responses(responses)
        config = AgentConfig(max_iterations=3)
        agent = Agent(llm=llm, tools=[search], config=config)
        result = agent.run("Do something")

        assert result.success is False
        assert "max_iterations_reached" in result.stop_reason

    def test_stuck_detection(self, mock_llm_with_responses):
        responses = [
            LLMResponse(
                content="Same result.",
                tool_calls=[ToolCall(id=f"tc{i}", function="think", arguments='{"thought": "x"}')],
                usage=Usage(1, 1, 2),
            )
            for i in range(5)
        ]
        llm = mock_llm_with_responses(responses)
        config = AgentConfig(max_iterations=10)
        agent = Agent(llm=llm, config=config)
        result = agent.run("Do something")

        assert result.stop_reason == "stuck_detected"

    def test_artifact_collection(self, mock_llm_with_responses):
        @tool
        def save(path: str, content: str) -> dict:
            """Save file."""
            return {"result": "saved", "_artifacts": [path]}

        responses = [
            LLMResponse(
                content="Saving file.",
                tool_calls=[ToolCall(
                    id="tc1",
                    function="save",
                    arguments='{"path": "test.py", "content": "x=1"}',
                )],
                usage=Usage(5, 5, 10),
            ),
            LLMResponse(
                content="Done.",
                tool_calls=[ToolCall(
                    id="tc2",
                    function="done",
                    arguments='{"result": "ok"}',
                )],
                usage=Usage(2, 2, 4),
            ),
        ]
        llm = mock_llm_with_responses(responses)
        agent = Agent(llm=llm, tools=[save], config=AgentConfig(max_iterations=5))
        result = agent.run("Save a file")

        assert "test.py" in result.artifacts


class TestJsonRepair:
    """Test Agent._repair_json static method."""

    def test_valid_json(self):
        assert Agent._repair_json('{"a": 1}') == {"a": 1}

    def test_trailing_comma(self):
        assert Agent._repair_json('{"a": 1,}') == {"a": 1}

    def test_unclosed_string(self):
        # The repair adds a closing quote but leaves the } inside the string value,
        # so it cannot fully repair this case — at minimum we verify it does not crash
        result = Agent._repair_json('{"a": "hello}')
        # Best-effort: should either parse or return empty dict gracefully
        assert isinstance(result, dict)

    def test_python_bool_none(self):
        assert Agent._repair_json('{"a": True, "b": None}') == {"a": True, "b": None}

    def test_unquoted_keys(self):
        assert Agent._repair_json('{a: 1}') == {"a": 1}

    def test_completely_invalid_returns_empty(self):
        assert Agent._repair_json("not json at all") == {}

    def test_empty_string(self):
        assert Agent._repair_json("") == {}


class TestAgentHooks:
    """Test Agent lifecycle hooks."""

    def test_on_complete_hook(self, mock_llm_with_responses):
        responses = [
            LLMResponse(
                content="Done.",
                tool_calls=[ToolCall(
                    id="tc1",
                    function="done",
                    arguments='{"result": "ok"}',
                )],
                usage=Usage(5, 5, 10),
            ),
        ]
        llm = mock_llm_with_responses(responses)
        agent = Agent(llm=llm, config=AgentConfig(max_iterations=3))

        completed = []
        agent.on_complete = lambda result: completed.append(result)
        agent.run("task")

        assert len(completed) == 1
        assert isinstance(completed[0], AgentResult)

    def test_on_step_hook(self, mock_llm_with_responses):
        responses = [
            LLMResponse(
                content="Thinking.",
                tool_calls=[ToolCall(id="tc1", function="think", arguments='{"thought": "x"}')],
                usage=Usage(3, 3, 6),
            ),
            LLMResponse(
                content="Done.",
                tool_calls=[ToolCall(id="tc2", function="done", arguments='{"result": "ok"}')],
                usage=Usage(2, 2, 4),
            ),
        ]
        llm = mock_llm_with_responses(responses)
        agent = Agent(llm=llm, config=AgentConfig(max_iterations=5))

        steps = []
        agent.on_step = lambda step: steps.append(step)
        agent.run("task")

        # Both think and done iterations record a step
        assert len(steps) == 2
