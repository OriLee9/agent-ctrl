"""Individual artifact validators.

Each validator implements:
    validate(path: str, content: str | None = None) -> ValidationResult
"""
from __future__ import annotations

import ast
import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    validator: str
    path: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "validator": self.validator,
            "path": self.path,
            "passed": self.passed,
            "message": self.message,
            "details": self.details,
        }


class BaseValidator(ABC):
    """Base class for all validators."""

    name: str = "base"

    @abstractmethod
    def validate(self, path: str, content: str | None = None) -> ValidationResult:
        """Validate a single artifact.

        Args:
            path: File path (relative or absolute).
            content: Optional pre-loaded file content.

        Returns:
            ValidationResult.
        """

    def can_validate(self, path: str) -> bool:
        """Check if this validator applies to the given path.

        Override to filter by file extension, size, etc.
        """
        return True


class PythonSyntaxValidator(BaseValidator):
    """Validate Python source files for syntax errors."""

    name = "python_syntax"

    def can_validate(self, path: str) -> bool:
        return path.endswith(".py")

    def validate(self, path: str, content: str | None = None) -> ValidationResult:
        if content is None:
            if not os.path.exists(path):
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"File not found: {path}",
                )
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"Cannot read file: {e}",
                )

        try:
            ast.parse(content)
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=True,
                message="Python syntax OK",
            )
        except SyntaxError as e:
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=False,
                message=f"Syntax error at line {e.lineno}: {e.msg}",
                details={"line": e.lineno, "offset": e.offset, "text": e.text},
            )


class JsonValidator(BaseValidator):
    """Validate JSON files for well-formedness and schema."""

    name = "json"

    def can_validate(self, path: str) -> bool:
        return path.endswith(".json")

    def __init__(self, schema: dict[str, Any] | None = None):
        self.schema = schema

    def validate(self, path: str, content: str | None = None) -> ValidationResult:
        if content is None:
            if not os.path.exists(path):
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"File not found: {path}",
                )
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"Cannot read file: {e}",
                )

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=False,
                message=f"Invalid JSON: {e.msg} at line {e.lineno}",
                details={"line": e.lineno, "column": e.colno},
            )

        # Schema check (if provided)
        if self.schema is not None:
            # Simple schema check: verify keys exist
            missing = [
                key for key in self.schema.get("required", [])
                if key not in data
            ]
            if missing:
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"Missing required keys: {missing}",
                    details={"missing_keys": missing},
                )

        return ValidationResult(
            validator=self.name,
            path=path,
            passed=True,
            message="JSON valid",
        )


class FileExistsValidator(BaseValidator):
    """Validate that referenced files exist on disk."""

    name = "file_exists"

    def validate(self, path: str, content: str | None = None) -> ValidationResult:
        exists = os.path.exists(path)
        if exists:
            size = os.path.getsize(path)
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=True,
                message=f"File exists ({size:,} bytes)",
                details={"size_bytes": size},
            )
        return ValidationResult(
            validator=self.name,
            path=path,
            passed=False,
            message=f"File not found: {path}",
        )


class MarkdownFormatValidator(BaseValidator):
    """Validate that task output is a pure markdown document, not code."""

    name = "markdown_format"

    def validate(self, path: str, content: str | None = None) -> ValidationResult:
        if content is None:
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=False,
                message="No content provided for validation",
            )

        # Check for code file writing patterns
        if "write_file(" in content:
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=False,
                message="Output contains write_file() calls — design task should NOT write files",
            )

        # Check for HTML/JS/CSS code block patterns suggesting implementation
        impl_patterns = [
            (r"<script[\s>]", "HTML <script> tag"),
            (r"<html[\s>]", "HTML <html> tag"),
            (r"<style[\s>]", "HTML <style> tag"),
            (r"<!DOCTYPE\s+html", "HTML doctype"),
            (r"function\s+\w+\s*\([^)]*\)\s*\{", "JavaScript function definition"),
            (r"const\s+\w+\s*=\s*\{", "JavaScript object literal"),
            (r"import\s+\{[^}]+\}\s+from\s+['\"]", "ES module import"),
        ]
        for pattern, desc in impl_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"Output contains {desc} — design document should be text/markdown only",
                )

        # Check for markdown headers
        if not re.search(r"^#{1,6}\s", content, re.MULTILINE):
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=False,
                message="Output lacks markdown headers — expected structured markdown document",
            )

        return ValidationResult(
            validator=self.name,
            path=path,
            passed=True,
            message="Markdown format valid",
        )


class HtmlValidator(BaseValidator):
    """Validate HTML files for basic structural correctness."""

    name = "html"

    # Self-closing tags that don't need closing tags
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def can_validate(self, path: str) -> bool:
        return path.endswith(".html") or path.endswith(".htm")

    def validate(self, path: str, content: str | None = None) -> ValidationResult:
        if content is None:
            if not os.path.exists(path):
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"File not found: {path}",
                )
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"Cannot read file: {e}",
                )

        if not content.strip():
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=False,
                message="Empty HTML file",
            )

        # Check for unclosed tags using a simple stack
        errors = self._check_tags(content)
        if errors:
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=False,
                message="; ".join(errors[:3]),
                details={"errors": errors},
            )

        return ValidationResult(
            validator=self.name,
            path=path,
            passed=True,
            message="HTML structure valid",
        )

    def _check_tags(self, content: str) -> list[str]:
        """Check for unclosed/mismatched HTML tags."""
        errors: list[str] = []
        stack: list[str] = []
        # Find all tags: opening, closing, self-closing
        for match in re.finditer(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*(/?)>", content):
            slash_prefix = match.group(1)
            tag_name = match.group(2).lower()
            slash_suffix = match.group(3)

            if tag_name in self.VOID_TAGS:
                continue  # void tags don't need closing

            if slash_suffix:  # self-closing: <tag />
                continue

            if slash_prefix:  # closing tag: </tag>
                if not stack:
                    errors.append(f"Unexpected closing </{tag_name}>")
                elif stack[-1] != tag_name:
                    errors.append(
                        f"Mismatched tags: <{stack[-1]}> closed by </{tag_name}>"
                    )
                else:
                    stack.pop()
            else:  # opening tag
                stack.append(tag_name)

        if stack:
            errors.append(f"Unclosed tags: {', '.join(stack)}")

        return errors


class JavaScriptValidator(BaseValidator):
    """Validate JavaScript for basic syntax issues."""

    name = "javascript"

    def can_validate(self, path: str) -> bool:
        return path.endswith(".js")

    def validate(self, path: str, content: str | None = None) -> ValidationResult:
        if content is None:
            if not os.path.exists(path):
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"File not found: {path}",
                )
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return ValidationResult(
                    validator=self.name,
                    path=path,
                    passed=False,
                    message=f"Cannot read file: {e}",
                )

        if not content.strip():
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=False,
                message="Empty JS file",
            )

        # Check for common syntax issues
        errors = self._check_syntax(content)
        if errors:
            return ValidationResult(
                validator=self.name,
                path=path,
                passed=False,
                message="; ".join(errors[:3]),
                details={"errors": errors},
            )

        return ValidationResult(
            validator=self.name,
            path=path,
            passed=True,
            message="JavaScript syntax OK (basic checks)",
        )

    def _check_syntax(self, content: str) -> list[str]:
        """Run basic JS syntax checks."""
        errors: list[str] = []

        # Check brace balance
        brace_count = 0
        paren_count = 0
        bracket_count = 0
        in_string = False
        string_char = None
        i = 0
        while i < len(content):
            ch = content[i]
            if in_string:
                if ch == "\\" and i + 1 < len(content):
                    i += 2
                    continue
                if ch == string_char:
                    in_string = False
                    string_char = None
            else:
                if ch in ('"', "'", "`"):
                    in_string = True
                    string_char = ch
                elif ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    if brace_count < 0:
                        errors.append("Unmatched '}'")
                        brace_count = 0
                elif ch == "(":
                    paren_count += 1
                elif ch == ")":
                    paren_count -= 1
                    if paren_count < 0:
                        errors.append("Unmatched ')'")
                        paren_count = 0
                elif ch == "[":
                    bracket_count += 1
                elif ch == "]":
                    bracket_count -= 1
                    if bracket_count < 0:
                        errors.append("Unmatched ']'")
                        bracket_count = 0
            i += 1

        if brace_count > 0:
            errors.append(f"Unclosed '{{' ({brace_count} missing)")
        if paren_count > 0:
            errors.append(f"Unclosed '(' ({paren_count} missing)")
        if bracket_count > 0:
            errors.append(f"Unclosed '[' ({bracket_count} missing)")

        return errors
