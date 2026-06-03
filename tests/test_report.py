"""Tests for utils.report module."""
from __future__ import annotations

import json
import os
import tempfile
import time

import pytest

from utils.report import ReportGenerator, WorkflowReport


class TestWorkflowReport:
    """Test WorkflowReport dataclass."""

    def test_to_dict(self):
        report = WorkflowReport(
            workflow_name="test",
            workflow_id="wf_123",
            started_at=time.time(),
            completed_at=time.time(),
            total_elapsed=10.0,
            success=True,
            task_count=3,
            completed_count=2,
            failed_count=1,
            total_tokens={"prompt": 100, "completion": 50},
            artifacts=["file.py"],
        )
        d = report.to_dict()
        assert d["workflow_name"] == "test"
        assert d["success"] is True
        assert d["task_count"] == 3
        assert d["total_tokens"]["prompt"] == 100

    def test_success_property_all_passed(self):
        report = WorkflowReport(
            workflow_name="test",
            workflow_id="wf_1",
            started_at=time.time(),
            completed_at=time.time(),
            total_elapsed=1.0,
            success=True,
            task_count=1,
            completed_count=1,
            failed_count=0,
        )
        # Note: success is determined by passed==failed==0 and total>0,
        # but this WorkflowReport doesn't use ValidationSummary
        assert report.success is True


class TestReportGenerator:
    """Test ReportGenerator."""

    def test_make_run_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = ReportGenerator(base_outputs_dir=tmpdir)
            run_dir = gen._make_run_dir("test_workflow")
            assert os.path.isdir(run_dir)
            assert os.path.isdir(os.path.join(run_dir, "artifacts"))
            assert "test_workflow" in run_dir

    def test_collect_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = ReportGenerator(base_outputs_dir=tmpdir)
            run_dir = gen._make_run_dir("test")

            # Create a source file
            src = os.path.join(tmpdir, "source.py")
            with open(src, "w") as f:
                f.write("x = 1")

            collected = gen.collect_artifacts([src], run_dir)
            assert collected == ["source.py"]
            assert os.path.exists(os.path.join(run_dir, "artifacts", "source.py"))

    def test_collect_artifacts_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = ReportGenerator(base_outputs_dir=tmpdir)
            run_dir = gen._make_run_dir("test")
            collected = gen.collect_artifacts(["/nonexistent/file.py"], run_dir)
            assert collected == []

    def test_generate_markdown_success(self):
        report = WorkflowReport(
            workflow_name="game_dev",
            workflow_id="wf_abc",
            started_at=time.time(),
            completed_at=time.time(),
            total_elapsed=120.5,
            success=True,
            task_count=4,
            completed_count=4,
            failed_count=0,
            artifacts=["game.py", "index.html"],
        )
        gen = ReportGenerator()
        md = gen.generate_markdown(report)
        assert "# Workflow Report: game_dev" in md
        assert "✅ Success" in md
        assert "120.50s" in md
        assert "game.py" in md
        assert "index.html" in md

    def test_generate_markdown_with_validation(self):
        report = WorkflowReport(
            workflow_name="test",
            workflow_id="wf_1",
            started_at=time.time(),
            completed_at=time.time(),
            total_elapsed=5.0,
            success=True,
            task_count=1,
            completed_count=1,
            failed_count=0,
            validation_summary={
                "total": 3,
                "passed": 2,
                "failed": 1,
                "results": [
                    {
                        "validator": "python_syntax",
                        "path": "bad.py",
                        "passed": False,
                        "message": "Syntax error",
                    }
                ],
            },
        )
        gen = ReportGenerator()
        md = gen.generate_markdown(report)
        assert "Validation" in md
        assert "3" in md
        assert "bad.py" in md

    def test_generate_report_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = ReportGenerator(base_outputs_dir=tmpdir)

            # Create a fake artifact
            src_dir = os.path.join(tmpdir, "src")
            os.makedirs(src_dir)
            src_file = os.path.join(src_dir, "main.py")
            with open(src_file, "w") as f:
                f.write("print('hello')")

            run_dir = gen.generate_report(
                workflow_name="test_wf",
                workflow_id="wf_123",
                task_results={
                    "design": {"success": True, "output": "done", "elapsed": 5.0, "error": None, "artifacts": []},
                    "code": {"success": True, "output": "ok", "elapsed": 10.0, "error": None, "artifacts": [src_file]},
                },
                total_elapsed=15.0,
                success=True,
                artifact_paths=[src_file],
                total_tokens={"prompt": 100, "completion": 50},
            )

            assert os.path.isdir(run_dir)
            assert os.path.exists(os.path.join(run_dir, "report.md"))
            assert os.path.exists(os.path.join(run_dir, "report.json"))

            # Check JSON report
            with open(os.path.join(run_dir, "report.json"), "r") as f:
                data = json.load(f)
            assert data["workflow_name"] == "test_wf"
            assert data["success"] is True
            assert data["task_count"] == 2
            assert data["completed_count"] == 2

            # Check artifact collected
            assert os.path.exists(os.path.join(run_dir, "artifacts", "main.py"))
