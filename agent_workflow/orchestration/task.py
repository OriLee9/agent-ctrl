"""
Task层 — 对"要做什么"的描述。

设计参考:
- CrewAI [https://github.com/joaomdmoura/crewAI] 的Task概念
- LangGraph [https://github.com/langchain-ai/langgraph] 的StateGraph节点

原则:
- Task是数据的容器，不包含执行逻辑
- 与Agent解耦：一个Task可以被任何Agent执行
- 支持模板变量（jinja-style）用于动态输入
- 描述期望输出，方便后续验证
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Task:
    """
    任务定义。

    Attributes:
        name: 任务标识（唯一）
        description: 任务描述（给Agent看的指令）
        expected_output: 期望的输出格式/内容
        inputs: 输入数据（字典，支持模板变量）
        context: 额外的上下文信息
        agent_id: 指定执行此任务的Agent（Workflow中动态分配）
        dependencies: 依赖的其他任务名
    """
    name: str
    description: str
    expected_output: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    agent_id: str | None = None
    dependencies: list[str] = field(default_factory=list)

    def render_description(self, **kwargs: Any) -> str:
        """
        渲染任务描述，替换模板变量。

        支持 {{variable}} 语法:
            task = Task("greet", "Say hello to {{name}}")
            task.render_description(name="Alice")  # "Say hello to Alice"
        """
        text = self.description
        merged = {**self.inputs, **kwargs}
        for key, value in merged.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in text:
                text = text.replace(placeholder, str(value))
        return text

    def with_inputs(self, **kwargs: Any) -> "Task":
        """返回带有新输入的Task副本（函数式更新）。"""
        new_inputs = {**self.inputs, **kwargs}
        return Task(
            name=self.name,
            description=self.description,
            expected_output=self.expected_output,
            inputs=new_inputs,
            context=self.context,
            agent_id=self.agent_id,
            dependencies=self.dependencies,
        )

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Task):
            return NotImplemented
        return self.name == other.name
