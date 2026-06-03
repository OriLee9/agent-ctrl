"""Validation runner — orchestrate multiple validators on workflow artifacts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from validation.validators import BaseValidator, ValidationResult


@dataclass
class ValidationSummary:
    """Summary of all validation results."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    results: list[ValidationResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0 and self.total > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "success": self.success,
            "results": [r.to_dict() for r in self.results],
        }

    def to_markdown(self) -> str:
        """Generate a human-readable markdown report."""
        lines = [
            "## Validation Results",
            "",
            f"- **Total**: {self.total}",
            f"- **Passed**: {self.passed} ✅",
            f"- **Failed**: {self.failed} ❌",
            "",
        ]
        if not self.results:
            lines.append("*No artifacts to validate.*")
            return "\n".join(lines)

        # Group by path
        by_path: dict[str, list[ValidationResult]] = {}
        for r in self.results:
            by_path.setdefault(r.path, []).append(r)

        for path, results in by_path.items():
            all_passed = all(r.passed for r in results)
            icon = "✅" if all_passed else "❌"
            lines.append(f"### {icon} `{path}`")
            for r in results:
                status = "✅" if r.passed else "❌"
                lines.append(f"- {status} **{r.validator}**: {r.message}")
            lines.append("")

        return "\n".join(lines)


class ValidationRunner:
    """Run a collection of validators against a set of artifacts.

    Usage:
        runner = ValidationRunner()
        runner.add_validator(PythonSyntaxValidator())
        runner.add_validator(JsonValidator())
        summary = runner.run_all(
            artifacts=["src/main.py", "config.json"],
            base_dir="/path/to/outputs"
        )
        if not summary.success:
            print("Validation failed!")
    """

    def __init__(self):
        self._validators: list[BaseValidator] = []

    def add_validator(self, validator: BaseValidator) -> "ValidationRunner":
        """Add a validator to the runner."""
        self._validators.append(validator)
        return self

    def run_all(
        self,
        artifacts: list[str],
        base_dir: str = "",
    ) -> ValidationSummary:
        """Run all applicable validators against all artifacts.

        Args:
            artifacts: List of file paths (relative to base_dir or absolute).
            base_dir: Optional base directory to resolve relative paths.

        Returns:
            ValidationSummary.
        """
        import os

        summary = ValidationSummary()

        for artifact in artifacts:
            full_path = artifact
            if base_dir and not os.path.isabs(artifact):
                full_path = os.path.join(base_dir, artifact)

            for validator in self._validators:
                if not validator.can_validate(artifact):
                    continue
                result = validator.validate(full_path)
                summary.results.append(result)
                summary.total += 1
                if result.passed:
                    summary.passed += 1
                else:
                    summary.failed += 1

        return summary

    def run_on_directory(
        self,
        directory: str,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> ValidationSummary:
        """Run validators on all files in a directory.

        Args:
            directory: Root directory to scan.
            include_patterns: Optional glob patterns to include (e.g. ["*.py", "*.json"]).
            exclude_patterns: Optional glob patterns to exclude.

        Returns:
            ValidationSummary.
        """
        import fnmatch
        import os

        summary = ValidationSummary()

        for root, _dirs, files in os.walk(directory):
            for filename in files:
                rel_path = os.path.relpath(os.path.join(root, filename), directory)

                # Apply include filter
                if include_patterns:
                    if not any(fnmatch.fnmatch(filename, p) for p in include_patterns):
                        continue

                # Apply exclude filter
                if exclude_patterns:
                    if any(fnmatch.fnmatch(filename, p) for p in exclude_patterns):
                        continue

                for validator in self._validators:
                    if not validator.can_validate(filename):
                        continue
                    full_path = os.path.join(root, filename)
                    result = validator.validate(full_path)
                    summary.results.append(result)
                    summary.total += 1
                    if result.passed:
                        summary.passed += 1
                    else:
                        summary.failed += 1

        return summary
