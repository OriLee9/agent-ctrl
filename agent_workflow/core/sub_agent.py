"""
Sub-Agent工具 — 模型主动创建独立prompt的子Agent。

设计参考:
- AutoGen [https://github.com/microsoft/autogen] 的嵌套对话模式
- MiniCode-Agent [https://github.com/xu-kai-quan/MiniCode-Agent] 的子Agent隔离思路

核心机制:
1. spawn_sub_agent 是一个特殊的Tool，注册到父Agent中
2. 模型调用时传入: name, system_prompt, task, [tools]
3. ContextHub 创建子Agent的Conversation（独立上下文）
4. 子Agent运行task，结果返回给父Agent
5. 父Agent的Conversation中记录完整的子Agent执行过程

关键点:
- 子Agent有完全独立的上下文（通过ContextHub隔离）
- 子Agent可以配置独立的系统提示
- 子Agent可以指定不同的工具集（默认继承父Agent的）
- 执行结果自动汇总到父Agent的观察中
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.agent import Agent, AgentConfig
from core.llm import Message
from core.memory import Conversation
from core.tool import Tool, ToolResult, tool

if TYPE_CHECKING:
    from orchestration.context_hub import ContextHub


class SubAgentManager:
    """
    Sub-Agent管理器。

    负责:
    1. 创建子Agent的Conversation（通过ContextHub）
    2. 执行子Agent任务
    3. 将结果返回给父Agent
    """

    def __init__(
        self,
        parent_agent: Agent,
        hub: "ContextHub | None" = None,
        max_sub_depth: int = 1,
    ):
        self.parent_agent = parent_agent
        self.hub = hub
        self.max_sub_depth = max_sub_depth
        self._current_depth = 0

    def spawn(
        self,
        name: str,
        task: str,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
    ) -> str:
        """
        创建并运行子Agent。

        Args:
            name: 子Agent名称
            task: 分配给子Agent的任务
            system_prompt: 子Agent的系统提示（默认继承父Agent的）
            tools: 指定工具名列表（None=继承父Agent的所有工具）

        Returns:
            子Agent的执行结果文本
        """
        if self._current_depth >= self.max_sub_depth:
            return f"[ERROR] Max sub-agent depth ({self.max_sub_depth}) reached. Cannot spawn '{name}'."

        self._current_depth += 1
        try:
            # 1. 构建子Agent
            sub_llm = self.parent_agent.llm  # 继承父Agent的LLM

            # 确定工具
            if tools:
                selected_tools = [
                    self.parent_agent.get_tool(t)
                    for t in tools
                    if self.parent_agent.get_tool(t) is not None
                ]
            else:
                # 排除spawn_sub_agent避免递归
                selected_tools = [
                    t for t in self.parent_agent._tools.values()
                    if t.name != "spawn_sub_agent"
                ]

            sub_agent = Agent(
                llm=sub_llm,
                tools=selected_tools,
                config=AgentConfig(max_iterations=5),
                name=name,
                system_prompt=system_prompt or self.parent_agent.system_prompt,
            )

            # 2. 获取或创建Conversation
            conv = None
            full_name = f"{self.parent_agent.name}/{name}"

            if self.hub:
                conv = self.hub.get(full_name)
                if not conv:
                    conv = self.hub.register(full_name, sub_agent.system_prompt)
            else:
                conv = Conversation(session_id=full_name)
                if sub_agent.system_prompt:
                    conv.add_system(sub_agent.system_prompt)

            # 3. 运行子Agent
            result = sub_agent.run(task, conversation=conv)

            # 4. 构建结果摘要
            output = (
                f"=== Sub-Agent '{name}' Result ===\n"
                f"Success: {result.success}\n"
                f"Output: {result.output}\n"
                f"Iterations: {result.iterations}\n"
                f"Tokens: {result.total_usage.total_tokens if result.total_usage else 'N/A'}\n"
                f"Stop Reason: {result.stop_reason}\n"
                f"========================"
            )

            return output

        finally:
            self._current_depth -= 1

    def create_tool(self) -> Tool:
        """
        创建spawn_sub_agent工具。

        返回的Tool可以注册到父Agent中:
            manager = SubAgentManager(agent, hub)
            agent.register_tool(manager.create_tool())
        """
        manager = self  # 闭包引用

        @tool
        def spawn_sub_agent(
            name: str,
            task: str,
            system_prompt: str = "",
            tools: str = "",  # JSON数组字符串，如 '["search", "analyze"]'
        ) -> str:
            """
            Spawn a sub-agent with its own system prompt to handle a sub-task.

            Use this when you need specialized expertise or want to delegate a
            distinct sub-task to a dedicated agent with different instructions.

            Args:
                name: Sub-agent name (e.g., "coder", "researcher")
                task: The task to delegate
                system_prompt: Custom system prompt for the sub-agent.
                    If empty, inherits parent's system prompt.
                    Example: "You are an expert Python programmer."
                tools: JSON array of tool names to give the sub-agent.
                    If empty, inherits all parent's tools.
                    Example: '["search", "analyze"]'
            """
            tool_list = None
            if tools:
                try:
                    tool_list = json.loads(tools)
                    if not isinstance(tool_list, list):
                        tool_list = None
                except json.JSONDecodeError:
                    pass

            return manager.spawn(
                name=name,
                task=task,
                system_prompt=system_prompt or None,
                tools=tool_list,
            )

        return spawn_sub_agent
