"""Tests for validation validators (HtmlValidator, JavaScriptValidator)."""
from __future__ import annotations

import pytest

from validation.validators import (
    HtmlValidator,
    JavaScriptValidator,
    ValidationResult,
)


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
