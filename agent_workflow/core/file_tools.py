"""
FileContextManager 的工具注册 — 为 Agent ReAct 循环提供文件操作能力。

工具列表:
1. search_code     — 在代码文件中搜索匹配行
2. read_file_range — 按行范围读取文件
3. list_files      — 列出目录结构
4. file_summary    — 生成文件摘要
5. search_with_context — 搜索+自动读取上下文
6. run_command     — 执行本地 shell 命令

使用方式:
    from core.file_tools import FileTools
    ft = FileTools("/project/root")
    for tool in ft.get_tools():
        agent.register_tool(tool)

    # Agent ReAct 中:
    # > search_code(pattern="def foo", path="src")
    # > read_file_range(path="src/x.py", offset=234, limit=20)
    # > run_command("python simulate.py --config cfg.json", timeout=60)
"""
from __future__ import annotations

import shlex
import subprocess

from core.file_context import FileContextManager
from core.tool import tool


class FileTools:
    """
    文件工具集 — 包装 FileContextManager 为 Agent 可用的 @tool。

    自动处理路径解析（相对/绝对）、结果格式化（文本而非对象）。
    """

    def __init__(self, root: str = ".", cache_size: int = 50):
        self._ctx = FileContextManager(root=root, cache_size=cache_size)

    def get_tools(self) -> list:
        """返回所有文件工具（注册到 Agent）。"""
        return [
            self._search_code_tool(),
            self._read_file_range_tool(),
            self._list_files_tool(),
            self._file_summary_tool(),
            self._search_with_context_tool(),
            self._write_file_tool(),
            self._make_dir_tool(),
            self._run_command_tool(),
        ]

    def _write_file_tool(self):
        ctx = self._ctx

        @tool
        def write_file(path: str, content: str) -> str:
            """
            Write content to a file. Creates parent directories as needed.

            Use this to create or overwrite a file with the given content.
            The path is relative to the project workspace.

            Args:
                path: File path relative to project root (e.g., "src/index.html")
                content: Full content to write to the file

            Example:
                write_file("src/index.html", "<html>...</html>")
                write_file("game/car.js", "class Car { ... }")
            """
            result = ctx.write_file(path=path, content=content)
            if result["success"]:
                return {
                    "result": f"✓ Written {result['bytes']:,} bytes to {path}",
                    "_artifacts": [path],
                }
            return f"✗ Failed to write {path}: {result.get('error', 'unknown')}"

        return write_file

    def _make_dir_tool(self):
        ctx = self._ctx

        @tool
        def make_dir(path: str) -> str:
            """
            Create a directory (and any missing parents).

            Use this before writing multiple files into a new project directory.

            Args:
                path: Directory path relative to project root (e.g., "racing_game")

            Example:
                make_dir("racing_game/assets")
                make_dir("racing_game")
            """
            result = ctx.make_dir(path=path)
            if result["success"]:
                return f"✓ Created directory {path}"
            return f"✗ Failed to create {path}: {result.get('error', 'unknown')}"

        return make_dir

    def _search_code_tool(self):
        ctx = self._ctx

        @tool
        def search_code(
            pattern: str,
            path: str = ".",
            file_type: str = "",
            max_results: int = 30,
        ) -> str:
            """
            Search for a pattern in code files under the given path.

            Use this to find function definitions, variable usages, or any text pattern.
            Returns file paths with line numbers and matching content.

            Args:
                pattern: Search pattern (supports regex, e.g., "def foo", "class.*Bar")
                path: Directory to search in (default: current directory)
                file_type: File extension filter, e.g., ".py", ".js" (empty = all code files)
                max_results: Maximum number of matches to return (default: 30)

            Example:
                search_code("def calculate", path="src", file_type=".py")
                search_code("TODO|FIXME", path=".", max_results=20)
            """
            ft = file_type if file_type else None
            results = ctx.search_code(
                pattern=pattern,
                path=path,
                file_type=ft,
                max_results=max(max_results, 1),
                context_lines=1,
            )
            if not results:
                return f"No matches found for '{pattern}'"

            lines: list[str] = [f"Found {len(results)} match(es) for '{pattern}':\n"]
            current_file = ""
            for r in results:
                if r.path != current_file:
                    current_file = r.path
                    lines.append(f"\n--- {r.path} ---")
                lines.append(f"  Line {r.line_number}: {r.content[:120]}")

            return "\n".join(lines)

        return search_code

    def _read_file_range_tool(self):
        ctx = self._ctx

        @tool
        def read_file_range(
            path: str,
            offset: int = 1,
            limit: int = 50,
        ) -> str:
            """
            Read a specific range of lines from a file.

            Use this after search_code() to read the relevant section of a file.
            Avoid reading entire large files — always use offset + limit.

            Args:
                path: File path (relative to project root)
                offset: Starting line number (1-based, default: 1)
                limit: Number of lines to read (default: 50, max: 500)

            Example:
                read_file_range("src/main.py", offset=120, limit=30)
                read_file_range("README.md", offset=1, limit=20)
            """
            fslice = ctx.read_file_range(
                path=path,
                offset=offset,
                limit=min(limit, 500),
            )
            return fslice.content

        return read_file_range

    def _list_files_tool(self):
        ctx = self._ctx

        @tool
        def list_files(
            path: str = ".",
            max_depth: int = 3,
        ) -> str:
            """
            List the directory structure with file sizes and line counts.

            Use this to understand the project layout before searching.

            Args:
                path: Directory to list (default: current directory)
                max_depth: Maximum recursion depth (default: 3)

            Example:
                list_files("src", max_depth=2)
                list_files(".")
            """
            root = ctx.list_files(path=path, max_depth=max_depth)

            def render(node, depth: int = 0) -> list[str]:
                indent = "  " * depth
                if node.is_dir:
                    lines = [f"{indent}{node.name}/"]
                    for child in node.children:
                        lines.extend(render(child, depth + 1))
                    return lines
                else:
                    size = f"{node.size_bytes:,}B" if node.size_bytes else ""
                    lines = f"{node.total_lines:,}L" if node.total_lines else ""
                    info = f" ({size}, {lines})" if (size or lines) else ""
                    return [f"{indent}{node.name}{info}"]

            return "\n".join(render(root))

        return list_files

    def _file_summary_tool(self):
        ctx = self._ctx

        @tool
        def file_summary(path: str) -> str:
            """
            Get a summary of a file (imports, classes, functions, head/tail lines).

            Use this to quickly understand a file's structure without reading it all.

            Args:
                path: File path (relative to project root)

            Example:
                file_summary("src/models.py")
                file_summary("package.json")
            """
            summary = ctx.file_summary(path)
            lines: list[str] = [
                f"# {summary.path}",
                f"Type: {summary.mime_type or 'unknown'}",
                f"Size: {summary.size_bytes:,} bytes",
                f"Lines: {summary.total_lines:,}",
            ]

            if summary.imports:
                lines.append(f"\n## Imports ({len(summary.imports)}):")
                for imp in summary.imports[:15]:
                    lines.append(f"  {imp}")

            if summary.classes:
                lines.append(f"\n## Classes ({len(summary.classes)}):")
                for cls in summary.classes:
                    lines.append(f"  {cls}")

            if summary.functions:
                lines.append(f"\n## Functions ({len(summary.functions)}):")
                for fn in summary.functions[:20]:
                    lines.append(f"  {fn}")

            if summary.head_lines:
                lines.append(f"\n## First {len(summary.head_lines)} lines:")
                for i, hl in enumerate(summary.head_lines, 1):
                    lines.append(f"  {i}: {hl[:100]}")

            return "\n".join(lines)

        return file_summary

    def _search_with_context_tool(self):
        ctx = self._ctx

        @tool
        def search_with_context(
            pattern: str,
            path: str = ".",
            max_results: int = 10,
        ) -> str:
            """
            Search code and automatically read context around each match.

            This combines search_code() + read_file_range() for convenience.
            Best for initial exploration of unfamiliar code.

            Args:
                pattern: Search pattern
                path: Directory to search
                max_results: Maximum matches with context

            Example:
                search_with_context("class UserController", "src")
            """
            enriched = ctx.search_with_context(
                pattern=pattern,
                path=path,
                max_results=max(max_results, 1),
                read_context_lines=15,
            )
            if not enriched:
                return f"No matches for '{pattern}'"

            parts: list[str] = [f"Found {len(enriched)} match(es):\n"]
            for item in enriched:
                sr = item["search"]
                fslice = item["slice"]
                parts.append(f"\n{'='*60}")
                parts.append(f"Match: {sr.path}:{sr.line_number}")
                parts.append(f"{'='*60}")
                parts.append(fslice.content)

            return "\n".join(parts)

        return search_with_context

    def _run_command_tool(self):
        @tool
        def run_command(command: str, timeout: int = 30, cwd: str = "") -> str:
            """
            Execute a local shell command and return its output.

            Use this to run simulation tools, build scripts, tests, or any external
            program. The command runs in a subprocess with captured stdout/stderr.

            Args:
                command: The command to execute (e.g. "python simulate.py --config cfg.json").
                         Spaces will be split via shlex; quote arguments containing spaces.
                timeout: Maximum seconds to wait (1-300, default: 30).
                cwd: Working directory for the command (default: current directory).

            Returns:
                Command stdout output, or an error message if the command fails.

            Examples:
                run_command("python run_simulation.py --config config.json")
                run_command("make build", cwd="./project", timeout=60)
                run_command("pytest tests/", timeout=120)
            """
            timeout = min(max(timeout, 1), 300)
            kwargs = {"capture_output": True, "text": True, "timeout": timeout}
            if cwd:
                kwargs["cwd"] = cwd

            try:
                # Prefer shlex.split for proper quoting; fall back to shell if parsing fails
                try:
                    cmd_parts = shlex.split(command)
                except ValueError:
                    cmd_parts = command
                result = subprocess.run(cmd_parts, **kwargs)
                output = result.stdout.strip()
                if result.returncode != 0:
                    err = result.stderr.strip() or "(no stderr)"
                    return (
                        f"[ERROR] Exit code {result.returncode}: {err[:500]}\n"
                        f"Stdout: {output[:500]}"
                    )
                return output or "(command completed with no output)"
            except subprocess.TimeoutExpired:
                return f"[ERROR] Command timed out after {timeout}s"
            except FileNotFoundError as e:
                return f"[ERROR] Command not found: {e}"
            except Exception as e:
                return f"[ERROR] {type(e).__name__}: {e}"

        return run_command
