"""Tests for core.file_context module — search_code stdout None bug fix."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from core.file_context import FileContextManager, SearchResult


class TestParseGrepOutput:
    """Test _parse_grep_output defensive handling of None/empty stdout."""

    def test_none_stdout_returns_empty(self, tmp_path):
        """Regression: _parse_grep_output(None, ...) must not raise AttributeError."""
        ctx = FileContextManager(root=str(tmp_path))
        results = ctx._parse_grep_output(None, context_lines=2, max_results=50)
        assert results == []

    def test_empty_string_stdout_returns_empty(self, tmp_path):
        """Empty grep output should return empty list."""
        ctx = FileContextManager(root=str(tmp_path))
        results = ctx._parse_grep_output("", context_lines=2, max_results=50)
        assert results == []

    def test_valid_grep_output_parsed_correctly(self, tmp_path):
        """Normal grep output is parsed into SearchResult objects."""
        ctx = FileContextManager(root=str(tmp_path))
        stdout = "foo.py:10:def hello():\nfoo.py:20:def world():"
        results = ctx._parse_grep_output(stdout, context_lines=0, max_results=50)
        assert len(results) == 2
        assert results[0].path == "foo.py"
        assert results[0].line_number == 10
        assert results[0].content == "def hello():"
        assert results[1].path == "foo.py"
        assert results[1].line_number == 20

    def test_malformed_lines_skipped(self, tmp_path):
        """Lines that don't match grep -n format are silently skipped."""
        ctx = FileContextManager(root=str(tmp_path))
        stdout = "foo.py:10:def hello():\nbad-line-no-colon\nfoo.py:20:def world():"
        results = ctx._parse_grep_output(stdout, context_lines=0, max_results=50)
        assert len(results) == 2


class TestSearchCodeStdoutNone:
    """Test search_code when subprocess.run returns stdout=None (non-zero exit)."""

    def test_subprocess_stdout_none_fallback(self, tmp_path):
        """
        Regression: grep exits with non-zero code and stdout is None.
        Before fix: 'NoneType' object has no attribute 'splitlines'
        After fix: returns empty list without crashing.
        """
        ctx = FileContextManager(root=str(tmp_path))

        # Mock subprocess.run to return stdout=None (simulates grep error exit)
        mock_result = MagicMock()
        mock_result.stdout = None

        with patch("subprocess.run", return_value=mock_result):
            results = ctx.search_code(pattern="def foo", path=str(tmp_path))
            assert results == []

    def test_subprocess_stdout_empty_no_matches(self, tmp_path):
        """grep returns empty string → no matches found."""
        ctx = FileContextManager(root=str(tmp_path))

        mock_result = MagicMock()
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            results = ctx.search_code(pattern="def foo", path=str(tmp_path))
            assert results == []

    def test_file_not_found_falls_back_to_python_search(self, tmp_path):
        """When grep binary is missing, FileNotFoundError triggers fallback."""
        ctx = FileContextManager(root=str(tmp_path))

        # Create a small file to search
        (tmp_path / "test.py").write_text("def hello():\n    pass\n")

        with patch("subprocess.run", side_effect=FileNotFoundError("grep not found")):
            results = ctx.search_code(pattern="def hello", path=str(tmp_path))
            assert len(results) == 1
            assert results[0].line_number == 1
            assert "def hello" in results[0].content


class TestSearchCodeIntegration:
    """Lightweight integration tests with real files."""

    def test_search_finds_content_via_mock(self, tmp_path):
        """End-to-end with mocked grep: create file, search, verify results."""
        ctx = FileContextManager(root=str(tmp_path))
        src = tmp_path / "src"
        src.mkdir()
        py_file = src / "app.py"
        py_file.write_text("def main():\n    print('hello')\n\ndef helper():\n    pass\n")

        # Mock grep stdout with line pointing to the real file
        abs_path = str(py_file)
        mock_result = MagicMock()
        mock_result.stdout = f"{abs_path}:1:def main():\n{abs_path}:4:def helper():\n"

        with patch("subprocess.run", return_value=mock_result):
            results = ctx.search_code(pattern="def ", path=str(src))
            assert len(results) == 2
            assert all(r.path.endswith("app.py") for r in results)

    def test_search_nonexistent_path_returns_empty(self, tmp_path):
        """Searching a path that doesn't exist returns empty list."""
        ctx = FileContextManager(root=str(tmp_path))
        results = ctx.search_code(pattern="foo", path=str(tmp_path / "nonexistent"))
        assert results == []


class TestWriteFileVersioning:
    """P3: Test versioned artifact archiving into versions/ subdirectory."""

    def test_first_write_creates_no_versions(self, tmp_path):
        """First write should not create a versions directory."""
        ctx = FileContextManager(root=str(tmp_path))
        result = ctx.write_file("game.js", "console.log('v1');")
        assert result["success"] is True
        assert (tmp_path / "game.js").read_text() == "console.log('v1');"
        assert not (tmp_path / "versions").exists()

    def test_second_write_archives_to_versions(self, tmp_path):
        """Second write should archive old version to versions/{timestamp}/."""
        ctx = FileContextManager(root=str(tmp_path))
        ctx.write_file("game.js", "console.log('v1');")
        ctx.write_file("game.js", "console.log('v2');")

        assert (tmp_path / "game.js").read_text() == "console.log('v2');"
        versions_dir = tmp_path / "versions"
        assert versions_dir.exists()
        # 应该有一个时间戳子目录
        subdirs = [d for d in versions_dir.iterdir() if d.is_dir()]
        assert len(subdirs) == 1
        # 子目录中应该有 game.js 的备份
        backup = subdirs[0] / "game.js"
        assert backup.exists()
        assert backup.read_text() == "console.log('v1');"

    def test_multiple_writes_create_multiple_versions(self, tmp_path):
        """Multiple overwrites should archive each old version."""
        ctx = FileContextManager(root=str(tmp_path))
        ctx.write_file("game.js", "v1")
        ctx.write_file("game.js", "v2")
        ctx.write_file("game.js", "v3")

        assert (tmp_path / "game.js").read_text() == "v3"
        versions_dir = tmp_path / "versions"
        assert versions_dir.exists()
        # 所有旧版本备份都应在 versions/ 下的某个子目录中
        all_backups = list(versions_dir.rglob("game.js*"))
        # 同一秒内写入可能进入同一目录（文件名重命名区分），也可能分目录
        assert len(all_backups) == 2  # v1 和 v2 的备份
        backup_texts = {b.read_text() for b in all_backups}
        assert backup_texts == {"v1", "v2"}

    def test_version_archive_preserves_nested_paths(self, tmp_path):
        """Archiving should work for nested file paths."""
        ctx = FileContextManager(root=str(tmp_path))
        ctx.write_file("src/game.js", "v1")
        ctx.write_file("src/game.js", "v2")

        assert (tmp_path / "src" / "game.js").read_text() == "v2"
        # versions 目录应在 src/ 下
        versions_dir = tmp_path / "src" / "versions"
        assert versions_dir.exists()
        subdirs = [d for d in versions_dir.iterdir() if d.is_dir()]
        assert len(subdirs) == 1
        assert (subdirs[0] / "game.js").read_text() == "v1"

    def test_workspace_stays_clean_no_clutter(self, tmp_path):
        """Workspace root should not contain timestamp-suffixed backup files."""
        ctx = FileContextManager(root=str(tmp_path))
        ctx.write_file("index.html", "<html>v1</html>")
        ctx.write_file("index.html", "<html>v2</html>")

        # 根目录下应该只有 index.html 和 versions/ 目录
        root_items = {p.name for p in tmp_path.iterdir()}
        assert "index.html" in root_items
        assert "versions" in root_items
        # 不应该有类似 index.html.0603_143052 的文件
        clutter = [p for p in tmp_path.iterdir() if p.name.startswith("index.html.")]
        assert len(clutter) == 0

