"""HTML / JS artifact validators used by the workflow engine.

Only HtmlValidator and JavaScriptValidator are kept — the rest were
only used by the now-deleted ValidationRunner.
"""
from __future__ import annotations

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
        """Validate a single artifact."""

    def can_validate(self, path: str) -> bool:
        return True


class HtmlValidator(BaseValidator):
    """Validate HTML files for basic structural correctness."""

    name = "html"

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
                    validator=self.name, path=path, passed=False,
                    message=f"File not found: {path}",
                )
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return ValidationResult(
                    validator=self.name, path=path, passed=False,
                    message=f"Cannot read file: {e}",
                )

        if not content.strip():
            return ValidationResult(
                validator=self.name, path=path, passed=False,
                message="Empty HTML file",
            )

        errors = self._check_tags(content)
        if errors:
            return ValidationResult(
                validator=self.name, path=path, passed=False,
                message="; ".join(errors[:3]),
                details={"errors": errors},
            )

        return ValidationResult(
            validator=self.name, path=path, passed=True,
            message="HTML structure valid",
        )

    def _check_tags(self, content: str) -> list[str]:
        """Check for unclosed/mismatched HTML tags."""
        errors: list[str] = []
        stack: list[str] = []
        for match in re.finditer(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*(/?)>", content):
            slash_prefix = match.group(1)
            tag_name = match.group(2).lower()
            slash_suffix = match.group(3)

            if tag_name in self.VOID_TAGS:
                continue
            if slash_suffix:
                continue
            if slash_prefix:
                if not stack:
                    errors.append(f"Unexpected closing </{tag_name}>")
                elif stack[-1] != tag_name:
                    errors.append(
                        f"Mismatched tags: <{stack[-1]}> closed by </{tag_name}>"
                    )
                else:
                    stack.pop()
            else:
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
                    validator=self.name, path=path, passed=False,
                    message=f"File not found: {path}",
                )
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return ValidationResult(
                    validator=self.name, path=path, passed=False,
                    message=f"Cannot read file: {e}",
                )

        if not content.strip():
            return ValidationResult(
                validator=self.name, path=path, passed=False,
                message="Empty JS file",
            )

        errors = self._check_syntax(content)
        if errors:
            return ValidationResult(
                validator=self.name, path=path, passed=False,
                message="; ".join(errors[:3]),
                details={"errors": errors},
            )

        return ValidationResult(
            validator=self.name, path=path, passed=True,
            message="JavaScript syntax OK (basic checks)",
        )

    def _check_syntax(self, content: str) -> list[str]:
        """Run basic JS syntax checks."""
        errors: list[str] = []
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
