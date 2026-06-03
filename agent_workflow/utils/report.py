"""Workflow artifact aggregation and report generation.

Usage:
    from utils.report import ReportGenerator
    gen = ReportGenerator(outputs_dir="outputs/my_workflow")
    gen.generate_report(
        workflow_name="my_workflow",
        workflow_id="wf_abc123",
        task_results={...},
        validation_summary=None,
    )
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WorkflowReport:
    """Structured workflow execution report."""

    workflow_name: str
    workflow_id: str
    started_at: float
    completed_at: float
    total_elapsed: float
    success: bool
    task_count: int
    completed_count: int
    failed_count: int
    total_tokens: dict[str, int] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    validation_summary: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "workflow_id": self.workflow_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_elapsed": self.total_elapsed,
            "success": self.success,
            "task_count": self.task_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "total_tokens": self.total_tokens,
            "artifacts": self.artifacts,
            "validation_summary": self.validation_summary,
            "error": self.error,
        }


class ReportGenerator:
    """Generate workflow execution reports and aggregate artifacts.

    Each workflow run gets its own timestamped output directory:
        outputs/{workflow_name}/{timestamp}/
            ├── report.md          # Human-readable summary
            ├── report.json        # Machine-readable summary
            └── artifacts/         # Collected artifact files
    """

    def __init__(self, base_outputs_dir: str | None = None):
        _pkg_dir = os.path.dirname(os.path.dirname(__file__))
        self.base_outputs_dir = base_outputs_dir or os.environ.get(
            "AGENT_OUTPUTS_DIR", os.path.join(_pkg_dir, "outputs")
        )

    def _make_run_dir(self, workflow_name: str) -> str:
        """Create a timestamped run directory."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(self.base_outputs_dir, workflow_name, ts)
        os.makedirs(run_dir, exist_ok=True)
        os.makedirs(os.path.join(run_dir, "artifacts"), exist_ok=True)
        return run_dir

    def collect_artifacts(
        self,
        artifact_paths: list[str],
        run_dir: str,
    ) -> list[str]:
        """Copy artifacts into the run directory.

        Args:
            artifact_paths: List of source file paths.
            run_dir: Target run directory.

        Returns:
            List of collected artifact names (relative to run_dir/artifacts/).
        """
        artifact_dir = os.path.join(run_dir, "artifacts")
        collected: list[str] = []

        for src_path in artifact_paths:
            if not os.path.exists(src_path):
                continue
            # Preserve relative structure if possible
            basename = os.path.basename(src_path)
            dst_path = os.path.join(artifact_dir, basename)
            # Handle name collisions
            counter = 1
            original_dst = dst_path
            while os.path.exists(dst_path):
                name, ext = os.path.splitext(basename)
                dst_path = os.path.join(artifact_dir, f"{name}_{counter}{ext}")
                counter += 1

            try:
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dst_path)
                elif os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path)
                rel = os.path.relpath(dst_path, artifact_dir)
                collected.append(rel)
            except Exception:
                continue

        return collected

    def generate_markdown(self, report: WorkflowReport) -> str:
        """Generate a human-readable markdown report."""
        lines: list[str] = [
            f"# Workflow Report: {report.workflow_name}",
            "",
            f"- **Workflow ID**: `{report.workflow_id}`",
            f"- **Status**: {'✅ Success' if report.success else '❌ Failed'}",
            f"- **Duration**: {report.total_elapsed:.2f}s",
            f"- **Tasks**: {report.completed_count}/{report.task_count} completed",
            f"- **Failed Tasks**: {report.failed_count}",
            "",
            "## Token Usage",
            "",
        ]

        if report.total_tokens:
            for key, value in report.total_tokens.items():
                lines.append(f"- **{key}**: {value:,}")
        else:
            lines.append("*No token usage data available.*")

        lines.extend([
            "",
            "## Artifacts",
            "",
        ])

        if report.artifacts:
            for art in report.artifacts:
                lines.append(f"- `{art}`")
        else:
            lines.append("*No artifacts produced.*")

        if report.validation_summary is not None:
            lines.extend([
                "",
                "## Validation",
                "",
            ])
            vs = report.validation_summary
            if isinstance(vs, dict):
                total = vs.get("total", 0)
                passed = vs.get("passed", 0)
                failed = vs.get("failed", 0)
                lines.append(f"- **Total Checks**: {total}")
                lines.append(f"- **Passed**: {passed} ✅")
                lines.append(f"- **Failed**: {failed} ❌")
                if failed > 0:
                    lines.append("")
                    lines.append("### Failed Checks")
                    for r in vs.get("results", []):
                        if not r.get("passed"):
                            lines.append(f"- `{r['path']}` — {r['validator']}: {r['message']}")
            else:
                lines.append(str(vs))

        if report.error:
            lines.extend([
                "",
                "## Error",
                "",
                f"```\n{report.error}\n```",
            ])

        lines.extend([
            "",
            "---",
            f"*Generated at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report.completed_at))}*",
        ])

        return "\n".join(lines)

    def generate_report(
        self,
        workflow_name: str,
        workflow_id: str,
        task_results: dict[str, Any],
        started_at: float | None = None,
        completed_at: float | None = None,
        total_elapsed: float = 0.0,
        success: bool = False,
        total_tokens: dict[str, int] | None = None,
        artifact_paths: list[str] | None = None,
        validation_summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> str:
        """Generate a complete workflow report.

        Args:
            workflow_name: Workflow name.
            workflow_id: Workflow ID.
            task_results: Dict of task_name -> task_result data.
            started_at: Start timestamp.
            completed_at: End timestamp.
            total_elapsed: Total elapsed time in seconds.
            success: Whether workflow succeeded.
            total_tokens: Token usage summary.
            artifact_paths: Source artifact paths to collect.
            validation_summary: Validation summary dict.
            error: Error message if workflow failed.

        Returns:
            Path to the generated run directory.
        """
        now = time.time()
        run_dir = self._make_run_dir(workflow_name)

        # Collect artifacts
        collected: list[str] = []
        if artifact_paths:
            collected = self.collect_artifacts(artifact_paths, run_dir)

        # Build report
        report = WorkflowReport(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            started_at=started_at or now,
            completed_at=completed_at or now,
            total_elapsed=total_elapsed,
            success=success,
            task_count=len(task_results),
            completed_count=sum(
                1 for r in task_results.values()
                if getattr(r, "success", False) or r.get("success", False)
            ),
            failed_count=sum(
                1 for r in task_results.values()
                if not (getattr(r, "success", False) or r.get("success", False))
            ),
            total_tokens=total_tokens or {},
            artifacts=collected,
            validation_summary=validation_summary,
            error=error,
        )

        # Write markdown report
        md_path = os.path.join(run_dir, "report.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.generate_markdown(report))

        # Write JSON report
        json_path = os.path.join(run_dir, "report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

        return run_dir
