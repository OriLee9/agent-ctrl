"""Tests for validation module."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from validation import (
    FileExistsValidator,
    JsonValidator,
    PythonSyntaxValidator,
    ValidationRunner,
)
from validation.validators import (
    HtmlValidator,
    JavaScriptValidator,
    MarkdownFormatValidator,
    ValidationResult,
)


class TestPythonSyntaxValidator:
    """Test PythonSyntaxValidator."""

    def test_valid_python(self):
        v = PythonSyntaxValidator()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            path = f.name
        try:
            result = v.validate(path)
            assert result.passed is True
            assert "syntax OK" in result.message
        finally:
            os.unlink(path)

    def test_invalid_python(self):
        v = PythonSyntaxValidator()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello(\n    return 'world'\n")
            path = f.name
        try:
            result = v.validate(path)
            assert result.passed is False
            assert "Syntax error" in result.message
        finally:
            os.unlink(path)

    def test_with_content_string(self):
        v = PythonSyntaxValidator()
        result = v.validate("test.py", content="x = 1 + 2")
        assert result.passed is True

    def test_missing_file(self):
        v = PythonSyntaxValidator()
        result = v.validate("/nonexistent/file.py")
        assert result.passed is False
        assert "not found" in result.message

    def test_can_validate_filter(self):
        v = PythonSyntaxValidator()
        assert v.can_validate("test.py") is True
        assert v.can_validate("test.json") is False
        assert v.can_validate("README.md") is False


class TestJsonValidator:
    """Test JsonValidator."""

    def test_valid_json(self):
        v = JsonValidator()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"key": "value", "num": 42}')
            path = f.name
        try:
            result = v.validate(path)
            assert result.passed is True
            assert "JSON valid" in result.message
        finally:
            os.unlink(path)

    def test_invalid_json(self):
        v = JsonValidator()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"key": "value",}')
            path = f.name
        try:
            result = v.validate(path)
            assert result.passed is False
            assert "Invalid JSON" in result.message
        finally:
            os.unlink(path)

    def test_with_content_string(self):
        v = JsonValidator()
        result = v.validate("config.json", content='{"name": "test"}')
        assert result.passed is True

    def test_can_validate_filter(self):
        v = JsonValidator()
        assert v.can_validate("test.json") is True
        assert v.can_validate("test.py") is False


class TestFileExistsValidator:
    """Test FileExistsValidator."""

    def test_existing_file(self):
        v = FileExistsValidator()
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("content")
            path = f.name
        try:
            result = v.validate(path)
            assert result.passed is True
            assert "exists" in result.message
        finally:
            os.unlink(path)

    def test_missing_file(self):
        v = FileExistsValidator()
        result = v.validate("/nonexistent/path")
        assert result.passed is False
        assert "not found" in result.message


class TestValidationRunner:
    """Test ValidationRunner."""

    def test_empty_run(self):
        runner = ValidationRunner()
        runner.add_validator(FileExistsValidator())
        summary = runner.run_all(artifacts=[])
        assert summary.total == 0
        assert summary.success is False  # No artifacts = not successful

    def test_single_validator(self):
        runner = ValidationRunner()
        runner.add_validator(FileExistsValidator())
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("hello")
            path = f.name
        try:
            summary = runner.run_all(artifacts=[path])
            assert summary.total == 1
            assert summary.passed == 1
            assert summary.failed == 0
            assert summary.success is True
        finally:
            os.unlink(path)

    def test_multiple_validators(self):
        runner = ValidationRunner()
        runner.add_validator(FileExistsValidator())
        runner.add_validator(PythonSyntaxValidator())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("x = 1\n")
            path = f.name
        try:
            summary = runner.run_all(artifacts=[path])
            # FileExists + PythonSyntax both run
            assert summary.total == 2
            assert summary.passed == 2
        finally:
            os.unlink(path)

    def test_run_on_directory(self):
        runner = ValidationRunner()
        runner.add_validator(FileExistsValidator())
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "a.py"), "w") as f:
                f.write("x = 1")
            with open(os.path.join(tmpdir, "b.txt"), "w") as f:
                f.write("hello")
            summary = runner.run_on_directory(
                tmpdir, include_patterns=["*.py"]
            )
            assert summary.total == 1
            assert summary.passed == 1

    def test_markdown_output(self):
        runner = ValidationRunner()
        runner.add_validator(FileExistsValidator())
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test")
            path = f.name
        try:
            summary = runner.run_all(artifacts=[path])
            md = summary.to_markdown()
            assert "Validation Results" in md
            assert "1" in md
        finally:
            os.unlink(path)


class TestHtmlValidator:
    """Test HtmlValidator."""

    def test_valid_html(self):
        v = HtmlValidator()
        html = "<html><head><title>X</title></head><body><p>Hello</p></body></html>"
        result = v.validate("test.html", content=html)
        assert result.passed is True
        assert "valid" in result.message

    def test_unclosed_tag(self):
        v = HtmlValidator()
        html = "<html><body><div><p>Hello</p></body></html>"
        result = v.validate("test.html", content=html)
        assert result.passed is False
        assert "Unclosed" in result.message

    def test_mismatched_tags(self):
        v = HtmlValidator()
        html = "<html><body><div></span></body></html>"
        result = v.validate("test.html", content=html)
        assert result.passed is False
        assert "Mismatched" in result.message

    def test_void_tags_ignored(self):
        v = HtmlValidator()
        html = "<html><body><img src='x.jpg'><br><hr></body></html>"
        result = v.validate("test.html", content=html)
        assert result.passed is True

    def test_self_closing_ok(self):
        v = HtmlValidator()
        html = "<html><body><input type='text' /></body></html>"
        result = v.validate("test.html", content=html)
        assert result.passed is True

    def test_empty_html(self):
        v = HtmlValidator()
        result = v.validate("test.html", content="")
        assert result.passed is False
        assert "Empty" in result.message

    def test_can_validate_filter(self):
        v = HtmlValidator()
        assert v.can_validate("test.html") is True
        assert v.can_validate("test.htm") is True
        assert v.can_validate("test.js") is False
        assert v.can_validate("test.py") is False

    def test_missing_file(self):
        v = HtmlValidator()
        result = v.validate("/nonexistent/file.html")
        assert result.passed is False
        assert "not found" in result.message


class TestJavaScriptValidator:
    """Test JavaScriptValidator."""

    def test_valid_js(self):
        v = JavaScriptValidator()
        js = "function hello() { return 'world'; }"
        result = v.validate("test.js", content=js)
        assert result.passed is True
        assert "OK" in result.message

    def test_unclosed_brace(self):
        v = JavaScriptValidator()
        js = "function hello() { return 'world';"
        result = v.validate("test.js", content=js)
        assert result.passed is False
        assert "Unclosed" in result.message

    def test_unmatched_brace(self):
        v = JavaScriptValidator()
        js = "function hello() { return 'world'; }}"
        result = v.validate("test.js", content=js)
        assert result.passed is False
        assert "Unmatched" in result.message

    def test_unmatched_paren(self):
        v = JavaScriptValidator()
        js = "console.log('hello';"
        result = v.validate("test.js", content=js)
        assert result.passed is False
        assert "Unclosed '('" in result.message

    def test_strings_ignored(self):
        v = JavaScriptValidator()
        js = 'const s = "{[()]}";'
        result = v.validate("test.js", content=js)
        assert result.passed is True

    def test_empty_js(self):
        v = JavaScriptValidator()
        result = v.validate("test.js", content="")
        assert result.passed is False
        assert "Empty" in result.message

    def test_can_validate_filter(self):
        v = JavaScriptValidator()
        assert v.can_validate("test.js") is True
        assert v.can_validate("test.html") is False
        assert v.can_validate("test.py") is False


class TestMarkdownFormatValidator:
    """Test MarkdownFormatValidator."""

    def test_valid_markdown(self):
        v = MarkdownFormatValidator()
        md = "# Design\n\n## Architecture\n\nSome text."
        result = v.validate("design.md", content=md)
        assert result.passed is True

    def test_contains_write_file(self):
        v = MarkdownFormatValidator()
        md = 'write_file("index.html", "...")'
        result = v.validate("design.md", content=md)
        assert result.passed is False
        assert "write_file" in result.message

    def test_contains_html(self):
        v = MarkdownFormatValidator()
        md = "<script>alert(1)</script>"
        result = v.validate("design.md", content=md)
        assert result.passed is False
        assert "script" in result.message

    def test_no_markdown_headers(self):
        v = MarkdownFormatValidator()
        md = "Just plain text without headers."
        result = v.validate("design.md", content=md)
        assert result.passed is False
        assert "markdown headers" in result.message


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_to_dict(self):
        vr = ValidationResult(
            validator="test",
            path="/tmp/file.py",
            passed=True,
            message="OK",
            details={"size": 100},
        )
        d = vr.to_dict()
        assert d["validator"] == "test"
        assert d["passed"] is True
        assert d["details"]["size"] == 100
