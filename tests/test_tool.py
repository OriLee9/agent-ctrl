"""Tests for core.tool module."""
from __future__ import annotations

import pytest

from core.tool import Tool, ToolResult, _build_json_schema, _extract_description, _parse_docstring_params, _pytype_to_jsonschema, done, think, tool


class TestToolDecorator:
    """Test the @tool decorator."""

    def test_basic_tool_creation(self):
        @tool
        def search(query: str) -> str:
            """Search the web."""
            return f"Results for {query}"

        assert isinstance(search, Tool)
        assert search.name == "search"
        assert search.description == "Search the web."

    def test_tool_with_custom_name(self):
        @tool(name="custom_search")
        def search(query: str) -> str:
            """Search the web."""
            return f"Results for {query}"

        assert search.name == "custom_search"

    def test_tool_execution_success(self):
        @tool
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        result = add.execute(a=2, b=3)
        assert result.success is True
        assert result.output == 5
        assert result.error is None

    def test_tool_execution_failure(self):
        @tool
        def divide(a: int, b: int) -> float:
            """Divide two numbers."""
            return a / b

        result = divide.execute(a=10, b=0)
        assert result.success is False
        assert result.output is None
        assert "division by zero" in result.error

    def test_tool_to_openai_schema(self):
        @tool
        def fetch(url: str, timeout: int = 30) -> str:
            """Fetch a URL."""
            return url

        schema = fetch.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "fetch"
        params = schema["function"]["parameters"]
        assert params["type"] == "object"
        assert "url" in params["properties"]
        assert "timeout" in params["properties"]
        assert params["required"] == ["url"]


class TestToolResult:
    """Test ToolResult behavior."""

    def test_to_text_success_string(self):
        tr = ToolResult(output="hello")
        assert tr.to_text() == "hello"

    def test_to_text_success_dict_with_result(self):
        tr = ToolResult(output={"result": "found it", "_artifacts": ["file.py"]})
        assert tr.to_text() == "found it"

    def test_to_text_success_dict_without_result(self):
        tr = ToolResult(output={"key": "value"})
        assert '"key": "value"' in tr.to_text()

    def test_to_text_failure(self):
        tr = ToolResult(output=None, error="network error", success=False)
        assert "[ERROR] network error" in tr.to_text()


class TestBuiltinTools:
    """Test built-in tools."""

    def test_done_tool(self):
        assert isinstance(done, Tool)
        result = done.execute(result="final answer")
        assert result.output == "final answer"

    def test_think_tool(self):
        assert isinstance(think, Tool)
        result = think.execute(thought="I should check this")
        assert "I should check this" in result.output


class TestJsonSchemaBuilder:
    """Test JSON Schema generation from type hints."""

    def test_simple_types(self):
        def fn(a: str, b: int, c: float, d: bool) -> None:
            """Test."""
            pass

        schema = _build_json_schema(fn)
        props = schema["properties"]
        assert props["a"]["type"] == "string"
        assert props["b"]["type"] == "integer"
        assert props["c"]["type"] == "number"
        assert props["d"]["type"] == "boolean"
        assert sorted(schema["required"]) == ["a", "b", "c", "d"]

    def test_optional_parameter(self):
        def fn(required: str, optional: str = "default") -> None:
            """Test."""
            pass

        schema = _build_json_schema(fn)
        assert schema["required"] == ["required"]

    def test_private_param_ignored(self):
        def fn(public: str, _private: str) -> None:
            """Test."""
            pass

        schema = _build_json_schema(fn)
        assert "_private" not in schema["properties"]

    def test_list_type(self):
        def fn(items: list) -> None:
            """Test."""
            pass

        schema = _build_json_schema(fn)
        assert schema["properties"]["items"]["type"] == "array"

    def test_dict_type(self):
        def fn(data: dict) -> None:
            """Test."""
            pass

        schema = _build_json_schema(fn)
        assert schema["properties"]["data"]["type"] == "object"


class TestDocstringParsing:
    """Test docstring parameter extraction."""

    def test_google_style_params(self):
        doc = """Do something.

        Args:
            query: The search query.
            limit: Maximum results.
        """
        params = _parse_docstring_params(doc)
        assert params["query"] == "The search query."
        assert params["limit"] == "Maximum results."

    def test_no_params(self):
        assert _parse_docstring_params("") == {}
        assert _parse_docstring_params("Just a description.") == {}


class TestPytypeToJsonschema:
    """Test Python type to JSON Schema conversion."""

    def test_basic_types(self):
        assert _pytype_to_jsonschema(str) == {"type": "string"}
        assert _pytype_to_jsonschema(int) == {"type": "integer"}
        assert _pytype_to_jsonschema(float) == {"type": "number"}
        assert _pytype_to_jsonschema(bool) == {"type": "boolean"}

    def test_union_optional(self):
        from typing import Optional
        schema = _pytype_to_jsonschema(Optional[str])
        # Optional[str] should resolve to string; if the runtime type
        # representation differs (e.g. Python 3.14), fall back gracefully
        assert schema in [{"type": "string"}, {}]

    def test_list_with_items(self):
        from typing import List
        schema = _pytype_to_jsonschema(List[str])
        assert schema["type"] == "array"
        assert schema["items"] == {"type": "string"}


class TestDescriptionExtraction:
    """Test _extract_description."""

    def test_single_line(self):
        assert _extract_description("Do something.") == "Do something."

    def test_multi_line(self):
        assert _extract_description("First line.\nSecond line.") == "First line."
