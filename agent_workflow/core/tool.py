"""
Tool层 — 外部能力的统一接口。

设计参考:
- smolagents [https://github.com/huggingface/smolagents] 的 @tool 装饰器思路
- OpenAI function calling 的 JSON Schema 标准 [https://platform.openai.com/docs/guides/function-calling]

原则:
- 定义Tool = 定义普通Python函数 + 装饰器
- 自动从类型注解+docstring推断JSON Schema
- 无额外依赖，纯标准库实现schema推断
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Union


@dataclass
class ToolResult:
    """工具执行结果的标准化包装。"""
    output: Any
    error: str | None = None
    success: bool = True

    def to_text(self) -> str:
        """转换为文本供LLM消费。"""
        if not self.success:
            return f"[ERROR] {self.error}"
        if isinstance(self.output, str):
            return self.output
        if isinstance(self.output, dict):
            # 优先取 result 字段（如 write_file 返回 {"result": "...", "_artifacts": [...]})
            return str(self.output.get("result", json.dumps(self.output, ensure_ascii=False)))
        return json.dumps(self.output, ensure_ascii=False, indent=2)


@dataclass
class Tool:
    """
    Tool的规范化表示。

    包含:
    - name: 工具名（LLM看到的标识）
    - description: 工具功能描述
    - parameters: JSON Schema for function calling
    - func: 实际执行的可调用对象
    """
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    func: Callable[..., Any]
    # 新增：工具是否可挂载到上下文管道做监控
    trackable: bool = True

    def execute(self, **kwargs: Any) -> ToolResult:
        """执行工具调用。"""
        try:
            result = self.func(**kwargs)
            return ToolResult(output=result)
        except Exception as e:
            return ToolResult(output=None, error=str(e), success=False)

    def to_openai_schema(self) -> dict[str, Any]:
        """转换为OpenAI function calling格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── 类型注解 → JSON Schema 的映射 ──────────────────────────────

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}


def _pytype_to_jsonschema(t: Any) -> dict[str, Any]:
    """将Python类型注解转换为JSON Schema片段。"""
    origin = getattr(t, "__origin__", None)
    args = getattr(t, "__args__", ())

    # 处理 Union / Optional
    if origin is type(Any) or t is Any:
        return {}

    # 处理 Optional[X] = Union[X, None]
    if origin is type(Union) or str(origin) == "typing.Union":
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _pytype_to_jsonschema(non_none[0])
        schemas = [_pytype_to_jsonschema(a) for a in non_none if a is not type(None)]
        # 简化: 如果只有一个非null类型
        if len(schemas) == 1:
            return schemas[0]
        return {"anyOf": schemas}

    # 处理 List[X]
    if origin is list or str(origin) in ("typing.List", "typing.Sequence"):
        item_schema = _pytype_to_jsonschema(args[0]) if args else {}
        return {"type": "array", "items": item_schema}

    # 处理 Dict[str, X]
    if origin is dict or str(origin) == "typing.Dict":
        return {"type": "object"}

    # 基本类型
    for py_type, json_type in _TYPE_MAP.items():
        if t is py_type:
            return {"type": json_type}

    return {}  # fallback: no schema constraint


def _parse_docstring_params(docstring: str) -> dict[str, str]:
    """
    从docstring中解析参数描述。
    支持 Google/NumPy 风格:

        Args:
            param1: description
            param2: description
    """
    if not docstring:
        return {}
    params: dict[str, str] = {}
    # 匹配 Args/Arguments 段落后的 param: description 行
    lines = docstring.split("\n")
    in_args = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower() in ("args:", "arguments:", "params:"):
            in_args = True
            continue
        if in_args:
            if not stripped or stripped.endswith(":"):
                break
            match = re.match(r"^(\w+)\s*:\s*(.+)$", stripped)
            if match:
                params[match.group(1)] = match.group(2)
            elif stripped.startswith("-") or stripped.startswith("*"):
                match = re.match(r"^[-*]\s*(\w+)\s*-\s*(.+)$", stripped)
                if match:
                    params[match.group(1)] = match.group(2)
    return params


def _build_json_schema(func: Callable) -> dict[str, Any]:
    """从函数签名和docstring构建JSON Schema。"""
    import typing

    sig = inspect.signature(func)
    docstring = inspect.getdoc(func) or ""
    param_docs = _parse_docstring_params(docstring)

    # 解析类型注解（处理from __future__ import annotations导致的字符串注解）
    try:
        type_hints = typing.get_type_hints(func)
    except Exception:
        type_hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name.startswith("_"):
            continue  # 跳过私有参数

        prop: dict[str, Any] = {}
        hint = type_hints.get(name)
        if hint is not None:
            schema = _pytype_to_jsonschema(hint)
            prop.update(schema)

        if name in param_docs:
            prop["description"] = param_docs[name]

        properties[name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema


def _extract_description(docstring: str) -> str:
    """提取docstring的第一句作为描述。"""
    if not docstring:
        return ""
    lines = docstring.strip().split("\n")
    first_line = lines[0].strip()
    return first_line


def tool(func: Callable | None = None, *, name: str | None = None) -> Tool:
    """
    将函数转换为Tool的装饰器/函数。

    使用方式:
        @tool
        def search(query: str) -> str:
            \"\"\"Search the web.\"\"\"
            ...

        @tool(name="custom_name")
        def my_tool(input: str) -> str:
            ...

        # 或者直接调用
        my_tool = tool(my_function)
    """
    def _make_tool(f: Callable) -> Tool:
        tool_name = name or f.__name__
        description = _extract_description(inspect.getdoc(f) or "")
        parameters = _build_json_schema(f)
        return Tool(
            name=tool_name,
            description=description,
            parameters=parameters,
            func=f,
        )

    if func is not None:
        return _make_tool(func)
    return _make_tool  # type: ignore[return-value]


# ── 内置常用工具 ────────────────────────────────────────────────

@tool
def done(result: str = "") -> str:
    """
    Mark the task as COMPLETE and return the final result.

    CALL THIS IMMEDIATELY when the task is done - do NOT continue working.
    Examples of when to call done:
    - After saving a file: done(result="File saved successfully")
    - After writing code: done(result="Code written and saved")
    - After answering a question: done(result="Your answer here")
    - After completing analysis: done(result="Analysis complete: ...")

    Args:
        result: Final result summary of the completed task.
    """
    return result


@tool
def think(thought: str) -> str:
    """
    记录当前思考过程。用于复杂推理时的中间步骤记录。

    Args:
        thought: 你的思考内容。
    """
    return f"[Thought recorded] {thought}"
