"""
Skill层 — 可复用的Agent能力包。

设计思路:
- Skill = 名称 + 描述 + 系统提示 + 工具集 + 可选参数
- SkillRegistry: 注册/加载/组合Skill
- Agent通过load_skill()获取能力
- Skill本身是纯数据，不绑定LLM

参考:
- LangChain [https://github.com/langchain-ai/langchain] 的Toolkit概念
- 但简化: Skill就是Prompt+Tools的组合，无额外抽象

原则:
- 一个Agent可加载多个Skill
- Skill可组合（Skill A + Skill B = 新Skill）
- Skill可参数化（模板变量替换）
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from core.tool import Tool


@dataclass
class Skill:
    """
    Skill — 可复用的Agent能力包。

    Attributes:
        name: Skill标识（唯一）
        description: Skill描述
        system_prompt: 系统提示模板（支持{{variable}}变量替换）
        tools: 工具集
        parameters: 参数定义（用于prompt模板变量）
        metadata: 额外元数据
    """
    name: str
    description: str
    system_prompt: str = ""
    tools: list[Tool] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def render_prompt(self, **kwargs: Any) -> str:
        """
        渲染系统提示，替换模板变量。

        支持 {{variable}} 语法:
            skill = Skill("coder", "Coding skill", "You are a {{language}} expert.")
            skill.render_prompt(language="Python")  # "You are a Python expert."
        """
        text = self.system_prompt
        merged = {**self.parameters, **kwargs}
        for key, value in merged.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in text:
                text = text.replace(placeholder, str(value))
        return text

    def with_params(self, **kwargs: Any) -> "Skill":
        """返回带有新参数的Skill副本（函数式更新）。"""
        new_params = {**self.parameters, **kwargs}
        return Skill(
            name=self.name,
            description=self.description,
            system_prompt=self.system_prompt,
            tools=self.tools.copy(),
            parameters=new_params,
            metadata=self.metadata.copy(),
        )

    def merge(self, other: "Skill") -> "Skill":
        """
        合并两个Skill（工具集取并集，提示词拼接）。

        用于组合多个Skill:
            combined = skill_coding.merge(skill_research)
        """
        existing_names = {t.name for t in self.tools}
        merged_tools = self.tools + [t for t in other.tools if t.name not in existing_names]

        merged_prompt = self.system_prompt
        if other.system_prompt:
            if merged_prompt:
                merged_prompt += "\n\n" + other.system_prompt
            else:
                merged_prompt = other.system_prompt

        return Skill(
            name=f"{self.name}+{other.name}",
            description=f"{self.description} + {other.description}",
            system_prompt=merged_prompt,
            tools=merged_tools,
            parameters={**self.parameters, **other.parameters},
            metadata={**self.metadata, **other.metadata},
        )

    def copy(self) -> "Skill":
        """深拷贝。"""
        return Skill(
            name=self.name,
            description=self.description,
            system_prompt=self.system_prompt,
            tools=self.tools.copy(),
            parameters=copy.deepcopy(self.parameters),
            metadata=copy.deepcopy(self.metadata),
        )


class SkillRegistry:
    """
    Skill注册表。

    使用方式:
        registry = SkillRegistry()

        # 注册Skill
        registry.register(Skill("coding", "Coding skill", "You are a Python expert.", [python_tool]))

        # 获取Skill
        skill = registry.get("coding")

        # 组合Skill
        combined = registry.combine(["coding", "research"])

        # 应用到Agent
        agent = Agent(llm=llm)
        registry.apply_to_agent("coding", agent, language="Rust")
    """

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """注册一个Skill。"""
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """获取Skill的副本（避免修改原始）。"""
        skill = self._skills.get(name)
        return skill.copy() if skill else None

    def list_skills(self) -> list[dict[str, Any]]:
        """列出所有已注册的Skill。"""
        return [
            {
                "name": s.name,
                "description": s.description,
                "tool_count": len(s.tools),
                "has_prompt": bool(s.system_prompt),
            }
            for s in self._skills.values()
        ]

    def combine(self, names: list[str]) -> Skill:
        """
        组合多个Skill为一个。

        组合顺序: 后加载的Skill的system_prompt追加到前面。
        """
        if not names:
            raise ValueError("At least one skill name required")

        combined = self.get(names[0])
        if not combined:
            raise ValueError(f"Skill '{names[0]}' not found")

        for name in names[1:]:
            skill = self.get(name)
            if not skill:
                raise ValueError(f"Skill '{name}' not found")
            combined = combined.merge(skill)

        combined.name = "+".join(names)
        return combined

    def apply_to_agent(self, name: str, agent: "Agent", **prompt_params: Any) -> None:
        """
        将Skill应用到Agent。

        这会:
        1. 注册Skill的工具到Agent
        2. 设置Agent的系统提示（Skill的system_prompt）
        """
        skill = self.get(name)
        if not skill:
            raise ValueError(f"Skill '{name}' not found")

        # 注册工具
        for tool in skill.tools:
            agent.register_tool(tool)

        # 设置系统提示
        if skill.system_prompt:
            rendered = skill.render_prompt(**prompt_params)
            agent.update_system_prompt(rendered)

    def unregister(self, name: str) -> bool:
        """注销Skill。"""
        if name in self._skills:
            del self._skills[name]
            return True
        return False

    def has(self, name: str) -> bool:
        """检查Skill是否存在。"""
        return name in self._skills


# ── 便捷函数 ────────────────────────────────────────────

def builtin_skills() -> SkillRegistry:
    """
    创建预置Skill的注册表。

    内置Skill:
    - coding: 编程能力
    - research: 研究能力（搜索、分析）
    - writing: 写作能力
    - review: 审查能力
    """
    from core.tool import tool

    @tool
    def code_execute(code: str, language: str = "python") -> str:
        """Execute code and return output."""
        return f"[Execution of {language} code completed]"

    @tool
    def code_review(code: str) -> str:
        """Review code for bugs and improvements."""
        return f"[Code review completed for {len(code)} chars]"

    @tool
    def search(query: str) -> str:
        """Search for information."""
        return f"[Search results for: {query}]"

    @tool
    def analyze(data: str) -> str:
        """Analyze data and provide insights."""
        return f"[Analysis: key findings from {len(data)} chars]"

    @tool
    def write(content: str, format: str = "markdown") -> str:
        """Write content in specified format."""
        return f"[Written {len(content)} chars in {format}]"

    @tool
    def review(content: str, criteria: str = "quality") -> str:
        """Review content against criteria."""
        return f"[Review: content passes {criteria} check]"

    registry = SkillRegistry()

    registry.register(Skill(
        name="coding",
        description="Programming and code execution",
        system_prompt="You are an expert programmer. You write clean, efficient, well-documented code.",
        tools=[code_execute, code_review],
        parameters={"language": "python"},
    ))

    registry.register(Skill(
        name="research",
        description="Information search and analysis",
        system_prompt="You are a thorough researcher. You search for accurate information and analyze findings critically.",
        tools=[search, analyze],
    ))

    registry.register(Skill(
        name="writing",
        description="Content writing and formatting",
        system_prompt="You are a skilled writer. You produce clear, engaging, well-structured content.",
        tools=[write],
        parameters={"format": "markdown"},
    ))

    registry.register(Skill(
        name="review",
        description="Content review and quality check",
        system_prompt="You are a meticulous reviewer. You check content for accuracy, clarity, and completeness.",
        tools=[review],
        parameters={"criteria": "quality"},
    ))

    return registry
