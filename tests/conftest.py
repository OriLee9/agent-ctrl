"""pytest shared fixtures."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add agent_workflow dir to path so internal imports like `from core.agent import ...` work
_FRAMEWORK_DIR = Path(__file__).resolve().parents[1] / "agent_workflow"
sys.path.insert(0, str(_FRAMEWORK_DIR))

import pytest

from core.llm import BaseLLM, LLMResponse, Message, ToolCall, Usage
from core.tool import tool


class MockLLM(BaseLLM):
    """Mock LLM for testing — returns preset responses."""

    def __init__(self, responses: list[LLMResponse] | None = None):
        self.responses = responses or []
        self.call_count = 0
        self.last_messages: list[list[Message]] = []
        self.last_tools: list[list[dict] | None] = []

    def model_id(self) -> str:
        return "mock:test"

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        stream_callback=None,
    ) -> LLMResponse:
        self.last_messages.append(messages)
        self.last_tools.append(tools)
        self.call_count += 1
        if self.call_count <= len(self.responses):
            return self.responses[self.call_count - 1]
        # Default: call done
        return LLMResponse(
            content="Done.",
            tool_calls=[ToolCall(id="done_1", function="done", arguments='{"result": "completed"}')],
            usage=Usage(5, 5, 10),
        )


@pytest.fixture
def mock_llm():
    """Return a fresh MockLLM with no preset responses."""
    return MockLLM()


@pytest.fixture
def mock_llm_with_responses():
    """Return a MockLLM factory that accepts a response list."""
    def _factory(responses: list[LLMResponse]) -> MockLLM:
        return MockLLM(responses=responses)
    return _factory


@pytest.fixture
def sample_tool():
    """A simple tool for testing."""
    @tool
    def greet(name: str) -> str:
        """Greet someone."""
        return f"Hello, {name}!"
    return greet


@pytest.fixture
def failing_tool():
    """A tool that always fails."""
    @tool
    def explode() -> str:
        """Explode."""
        raise RuntimeError("boom")
    return explode
