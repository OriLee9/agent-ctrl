"""Artifact validation layer — ensure workflow outputs meet quality standards.

Usage:
    from validation import ValidationRunner, ValidationResult
    runner = ValidationRunner()
    runner.add_validator(PythonSyntaxValidator())
    results = runner.run_all(artifacts=["src/main.py", "config.json"])
"""
from __future__ import annotations

from validation.runner import ValidationResult, ValidationRunner
from validation.validators import (
    FileExistsValidator,
    JsonValidator,
    PythonSyntaxValidator,
)

__all__ = [
    "ValidationRunner",
    "ValidationResult",
    "PythonSyntaxValidator",
    "JsonValidator",
    "FileExistsValidator",
]
