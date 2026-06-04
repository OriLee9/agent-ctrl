"""
Core layer — 4 essential abstractions for any agent system.

- LLM: Model interface
- Tool: External capability wrapper
- Memory: Context storage & snapshots
- Agent: ReAct reasoning loop
"""

from core.agent import Agent, AgentConfig, AgentResult
from core.llm import (
    BaseLLM,
    DeepSeekLLM,
    LLMResponse,
    Message,
    OpenAILLM,
    ToolCall,
    Usage,
    llm_from_env,
    resolve_deepseek_model,
)
from core.memory import Conversation, Snapshot, StepRecord
from core.tool import Tool, ToolResult, done, think, tool

__all__ = [
    # LLM
    "BaseLLM",
    "DeepSeekLLM",
    "OpenAILLM",
    "LLMResponse",
    "Message",
    "ToolCall",
    "Usage",
    "llm_from_env",
    "resolve_deepseek_model",
    # Tool
    "Tool",
    "ToolResult",
    "tool",
    "done",
    "think",
    # Memory
    "Conversation",
    "Snapshot",
    "StepRecord",
    # Agent
    "Agent",
    "AgentConfig",
    "AgentResult",
]
