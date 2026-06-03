"""
FileContextManager — 超大文件/超长上下文的轻量级解决方案。

设计原则（奥卡姆剃刀）:
- 不引入向量数据库、Embedding 等重型依赖
- 依赖系统工具（grep, git）+ Python 标准库
- 三层递进：检索 → 分段读取 → 缓存

核心能力:
1. search_code   — grep 模糊检索，返回 (文件, 行号, 匹配行)
2. read_file_range — offset/limit 分段读取，避免全量加载
3. list_files    — 目录树 + 文件元数据（大小/行数/类型）
4. file_summary  — 文件摘要（导入、类/函数签名、关键结构）
5. search_with_context — 检索 + 自动读取匹配点上下文

忽略规则:
- 自动加载 .gitignore（通过 git check-ignore）
- 支持 .agentignore（框架专用排除规则）
- 内置默认排除（node_modules, .git, __pycache__ 等）

缓存:
- LRU 文件内容缓存（默认 50 文件）
- 按 mtime 自动失效
"""
from __future__ import annotations

import fnmatch
import mimetypes
import os
import re
import subprocess
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


# ── 数据类 ────────────────────────────────────────────────────

@dataclass
class SearchResult:
    """单次搜索结果。"""

    path: str
    line_number: int
    content: str
    # 上下文行（前后各 N 行）
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines: list[str] = []
        for cb in self.context_before:
            lines.append(f"  {cb}")
        lines.append(f"> {self.content}")
        for ca in self.context_after:
            lines.append(f"  {ca}")
        return "\n".join(lines)


@dataclass
class FileSlice:
    """文件分段读取结果。"""

    path: str
    offset: int          # 起始行号（1-based）
    limit: int           # 请求行数
    actual_lines: int    # 实际读取行数
    content: str         # 文件内容
    total_lines: int | None = None  # 文件总行数（如已知）
    truncated: bool = False  # 是否被截断（超过安全限制）


@dataclass
class FileSummary:
    """文件摘要。"""

    path: str
    mime_type: str
    size_bytes: int
    total_lines: int
    # 代码文件特有
    imports: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    # 通用
    head_lines: list[str] = field(default_factory=list)   # 前 N 行
    tail_lines: list[str] = field(default_factory=list)   # 后 N 行


@dataclass
class FileNode:
    """目录树节点。"""

    name: str
    path: str
    is_dir: bool
    size_bytes: int = 0
    total_lines: int = 0
    mime_type: str = ""
    children: list["FileNode"] = field(default_factory=list)


# ── 忽略规则管理 ────────────────────────────────────────────

class IgnoreRuleManager:
    """
    管理文件排除规则。

    优先级（高到低）:
    1. .agentignore（框架专用）
    2. .gitignore（通过 git check-ignore）
    3. 内置默认排除列表
    """

    DEFAULT_IGNORE = {
        ".git", ".svn", ".hg", "__pycache__", ".pytest_cache",
        "node_modules", "vendor", ".idea", ".vscode", ".DS_Store",
        "*.pyc", "*.pyo", "*.so", "*.dylib", "*.dll",
        "*.min.js", "*.min.css", "*.map",
        "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.svg",
        "*.mp3", "*.mp4", "*.avi", "*.mov", "*.wav",
        "*.zip", "*.tar", "*.gz", "*.rar", "*.7z",
        "*.pdf", "*.doc", "*.docx", "*.xls", "*.xlsx",
        "*.ttf", "*.woff", "*.woff2", "*.eot",
        "build", "dist", "target", ".next", ".nuxt", ".svelte-kit",
        "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "coverage", ".coverage", "htmlcov",
        ".mypy_cache", ".ruff_cache", ".eslintcache",
    }

    def __init__(self, root: str = "."):
        self.root = os.path.abspath(root)
        self._agentignore_rules: list[str] = []
        self._gitignore_available = self._check_git()
        self._load_agentignore()

    def _check_git(self) -> bool:
        """检查当前目录是否在 git 仓库中。"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except Exception:
            return False

    def _load_agentignore(self) -> None:
        """加载 .agentignore 文件。"""
        path = os.path.join(self.root, ".agentignore")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self._agentignore_rules.append(line)

    def is_ignored(self, relpath: str) -> bool:
        """
        检查路径是否应被忽略。

        Args:
            relpath: 相对于 root 的路径
        """
        parts = relpath.split(os.sep)
        basename = parts[-1] if parts else relpath

        # 1. 内置默认排除
        for pattern in self.DEFAULT_IGNORE:
            if self._match(pattern, basename, relpath):
                return True

        # 2. .agentignore
        for rule in self._agentignore_rules:
            if self._match(rule, basename, relpath):
                return True

        # 3. .gitignore (通过 git check-ignore)
        if self._gitignore_available:
            try:
                result = subprocess.run(
                    ["git", "check-ignore", "-q", relpath],
                    cwd=self.root,
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True
            except Exception:
                pass

        return False

    @staticmethod
    def _match(pattern: str, basename: str, relpath: str) -> bool:
        """匹配忽略规则。"""
        parts = relpath.split("/")
        # 直接匹配文件名
        if pattern == basename:
            return True
        # fnmatch 通配符
        if fnmatch.fnmatch(basename, pattern):
            return True
        # 路径匹配（目录前缀）
        if relpath.startswith(pattern) or relpath.startswith(pattern + "/"):
            return True
        # 任意层级匹配（**/pattern）
        if pattern.startswith("**/"):
            suffix = pattern[3:]
            if suffix in parts:
                return True
        # pattern 以 / 结尾 = 目录匹配
        if pattern.endswith("/") and any(p.startswith(pattern.rstrip("/")) for p in parts):
            return True
        return False


# ── LRU 文件缓存 ────────────────────────────────────────────

class FileCache:
    """
    LRU 文件内容缓存，按 mtime 自动失效。

    缓存键：绝对路径
    缓存值：(mtime, content, line_count)
    """

    def __init__(self, max_size: int = 50):
        self._max_size = max_size
        # OrderedDict: 最近访问在尾部
        self._cache: OrderedDict[str, tuple[float, str, int]] = OrderedDict()

    def get(self, path: str) -> tuple[str, int] | None:
        """获取缓存内容，如过期返回 None。"""
        abs_path = os.path.abspath(path)
        if abs_path not in self._cache:
            return None

        cached_mtime, content, line_count = self._cache[abs_path]
        try:
            current_mtime = os.path.getmtime(abs_path)
        except OSError:
            del self._cache[abs_path]
            return None

        if current_mtime != cached_mtime:
            del self._cache[abs_path]
            return None

        # 移到尾部（最近访问）
        self._cache.move_to_end(abs_path)
        return content, line_count

    def put(self, path: str, content: str, line_count: int) -> None:
        """写入缓存。"""
        abs_path = os.path.abspath(path)
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            return

        if abs_path in self._cache:
            del self._cache[abs_path]
        elif len(self._cache) >= self._max_size:
            # 淘汰最久未访问
            self._cache.popitem(last=False)

        self._cache[abs_path] = (mtime, content, line_count)

    def invalidate(self, path: str) -> None:
        """手动失效缓存。"""
        abs_path = os.path.abspath(path)
        self._cache.pop(abs_path, None)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)

    def hit_rate(self, total_accesses: int) -> float:
        """计算命中率（需外部传入总访问次数）。"""
        if total_accesses == 0:
            return 0.0
        return min(self._cache.__len__() / total_accesses, 1.0)


# ── FileContextManager ──────────────────────────────────────

class FileContextManager:
    """
    文件上下文管理器 — Agent 的文件操作入口。

    典型使用模式（ReAct 循环）:
        1. search_code(pattern="def foo") → 定位到 x.py:234
        2. read_file_range("x.py", offset=220, limit=30) → 精确读取
        3. 如有需要 list_files() 了解项目结构
    """

    # 安全限制
    MAX_FILE_SIZE = 10 * 1024 * 1024   # 10MB 单文件上限
    MAX_SEARCH_RESULTS = 200
    MAX_READ_LINES = 500               # 单次最多读取 500 行
    MAX_TOTAL_LINES = 100 * 1024       # 100K 行文件视为超大文件

    # 代码文件扩展名
    CODE_EXTENSIONS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".kt", ".scala",
        ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift",
        ".rb", ".php", ".sh", ".bash", ".zsh", ".ps1", ".sql",
        ".html", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
        ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".cfg",
        ".md", ".rst", ".txt",
    }

    def __init__(self, root: str = ".", cache_size: int = 50):
        self.root = os.path.abspath(root)
        self._ignore = IgnoreRuleManager(root)
        self._cache = FileCache(max_size=cache_size)
        self._total_reads = 0
        self._cache_hits = 0

    # ── 内部辅助 ──────────────────────────────────────

    def _resolve_path(self, path: str) -> str:
        """将相对路径转为绝对路径（以 root 为基准）。

        自动处理 LLM 常见错误:
        - 重复包含根目录名: root=outputs/architect, path=architect/ARCHITECTURE.md
          → 自动去重: outputs/architect/ARCHITECTURE.md
        """
        if os.path.isabs(path):
            return path

        # 1. 相对 root
        candidate = os.path.normpath(os.path.join(self.root, path))

        root_name = os.path.basename(self.root.rstrip("/\\"))

        # 2. path 以根目录名开头 → 去重（确定性的，不依赖文件是否存在）
        if root_name and path.startswith(root_name + "/"):
            return os.path.normpath(os.path.join(self.root, path[len(root_name) + 1:]))

        # 3. 返回基于 root 的规范化路径（不再猜测父目录/兄弟目录）
        return candidate

    def _invalidate_cache(self, path: str) -> None:
        """写入后清除缓存中对应条目。"""
        abs_path = self._resolve_path(path)
        self._cache.invalidate(abs_path)

    # ── P0: 搜索 ──────────────────────────────────────

    def search_code(
        self,
        pattern: str,
        path: str = ".",
        file_type: str | None = None,
        max_results: int = 50,
        context_lines: int = 2,
        case_sensitive: bool = False,
        respect_ignore: bool = True,
    ) -> list[SearchResult]:
        """
        在代码文件中搜索匹配行（grep -r）。

        Args:
            pattern: 搜索模式（支持 grep 正则）
            path: 搜索起始路径（相对 root）
            file_type: 文件扩展名过滤（如 ".py"）
            max_results: 最大返回结果数
            context_lines: 上下文行数
            case_sensitive: 区分大小写
            respect_ignore: 遵守忽略规则

        Returns:
            SearchResult 列表，按文件分组排序
        """
        search_path = self._resolve_path(path)
        if not os.path.exists(search_path):
            return []

        cmd = self._build_grep_cmd(
            pattern, search_path, file_type, max_results,
            context_lines, case_sensitive, respect_ignore,
        )

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return []
        except FileNotFoundError:
            # grep 不可用（fallback 到 Python 实现）
            return self._search_fallback(
                pattern, search_path, file_type,
                max_results, context_lines, case_sensitive, respect_ignore,
            )

        stdout = result.stdout or ""
        return self._parse_grep_output(
            stdout, context_lines, max_results,
        )

    def _build_grep_cmd(
        self,
        pattern: str,
        search_path: str,
        file_type: str | None,
        max_results: int,
        context_lines: int,
        case_sensitive: bool,
        respect_ignore: bool,
    ) -> list[str]:
        """构建 grep 命令。"""
        cmd = ["grep", "-r", "-n", "-I"]  # -I 排除二进制文件

        if not case_sensitive:
            cmd.append("-i")

        # 上下文由 _parse_grep_output 自行读取文件获取，避免解析 grep -B/-A 的复杂输出

        # 文件类型过滤
        if file_type:
            cmd.extend(["--include", f"*{file_type}"])
        else:
            # 只搜索代码文件
            includes = []
            for ext in self.CODE_EXTENSIONS:
                includes.extend(["--include", f"*{ext}"])
            cmd.extend(includes)

        # 排除规则
        if respect_ignore:
            for item in IgnoreRuleManager.DEFAULT_IGNORE:
                if "*" in item:
                    cmd.extend(["--exclude", item])
                else:
                    cmd.extend(["--exclude-dir", item])

        cmd.extend(["-m", str(max_results)])
        cmd.append(pattern)
        cmd.append(search_path)

        return cmd

    def _parse_grep_output(
        self,
        stdout: str,
        context_lines: int,
        max_results: int,
    ) -> list[SearchResult]:
        """解析 grep -n 的输出，并自行读取文件获取上下文。"""
        results: list[SearchResult] = []
        if not stdout:
            return results

        for line in stdout.splitlines():
            match = re.match(r"^(.+):(\d+):(.*)$", line)
            if not match:
                continue

            file_path, line_num_str, content = match.groups()
            line_num = int(line_num_str)

            # 去掉 root 前缀，转为相对路径
            rel_path = file_path
            if rel_path.startswith(self.root):
                rel_path = rel_path[len(self.root):].lstrip("/\\")

            # 自行读取文件获取上下文（避免解析 grep -B/-A 的复杂合并输出）
            before: list[str] = []
            after: list[str] = []
            if context_lines > 0 and os.path.isfile(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    idx = line_num - 1  # 转为 0-based
                    start = max(0, idx - context_lines)
                    end = min(len(lines), idx + context_lines + 1)
                    before = [l.rstrip("\n") for l in lines[start:idx]]
                    after = [l.rstrip("\n") for l in lines[idx + 1:end]]
                except Exception:
                    pass

            results.append(
                SearchResult(
                    path=rel_path,
                    line_number=line_num,
                    content=content,
                    context_before=before,
                    context_after=after,
                )
            )
            if len(results) >= max_results:
                break

        return results

    def _search_fallback(
        self,
        pattern: str,
        search_path: str,
        file_type: str | None,
        max_results: int,
        context_lines: int,
        case_sensitive: bool,
        respect_ignore: bool,
    ) -> list[SearchResult]:
        """grep 不可用时的 Python fallback。"""
        results: list[SearchResult] = []
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)

        if os.path.isfile(search_path):
            files = [search_path]
        else:
            files = []
            for dirpath, dirnames, filenames in os.walk(search_path):
                # 过滤目录
                if respect_ignore:
                    dirnames[:] = [
                        d for d in dirnames
                        if not self._ignore.is_ignored(
                            os.path.relpath(os.path.join(dirpath, d), self.root)
                        )
                    ]
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    relp = os.path.relpath(fp, self.root)
                    if respect_ignore and self._ignore.is_ignored(relp):
                        continue
                    if file_type and not fn.endswith(file_type):
                        continue
                    files.append(fp)

        for fp in files:
            if len(results) >= max_results:
                break
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                continue

            rel = os.path.relpath(fp, self.root)
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    before = [
                        lines[j].rstrip("\n")
                        for j in range(max(0, i - context_lines - 1), i - 1)
                    ]
                    after = [
                        lines[j].rstrip("\n")
                        for j in range(i, min(len(lines), i + context_lines))
                    ]
                    results.append(SearchResult(
                        path=rel,
                        line_number=i,
                        content=line.rstrip("\n"),
                        context_before=before,
                        context_after=after,
                    ))
                    if len(results) >= max_results:
                        break

        return results

    # ── P0: 分段读取 ──────────────────────────────────

    def read_file_range(
        self,
        path: str,
        offset: int = 0,
        limit: int = 100,
        context_lines: int = 0,
    ) -> FileSlice:
        """
        按行范围读取文件（1-based 行号）。

        Args:
            path: 文件路径（相对 root 或绝对路径）
            offset: 起始行号（1-based，0 表示从第 1 行开始）
            limit: 最大读取行数
            context_lines: 额外读取的上下文行数（不算入 limit）

        Returns:
            FileSlice
        """
        abs_path = self._resolve_path(path)
        offset = max(1, offset) if offset > 0 else 1
        limit = min(limit, self.MAX_READ_LINES)

        self._total_reads += 1

        # 检查缓存
        cached = self._cache.get(abs_path)
        lines: list[str] = []
        total_lines: int | None = None

        if cached is not None:
            self._cache_hits += 1
            full_content, total_lines = cached
            lines = full_content.splitlines()
        else:
            # 检查文件大小
            try:
                size = os.path.getsize(abs_path)
            except OSError as e:
                return FileSlice(
                    path=path, offset=offset, limit=limit,
                    actual_lines=0, content=f"[Error: {e}]",
                )

            if size > self.MAX_FILE_SIZE:
                return FileSlice(
                    path=path, offset=offset, limit=limit,
                    actual_lines=0, content=f"[Error: File too large ({size:,} bytes > {self.MAX_FILE_SIZE:,} limit)]",
                )

            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    full_content = f.read()
                    lines = full_content.splitlines()
                    total_lines = len(lines)
                    self._cache.put(abs_path, full_content, total_lines)
            except Exception as e:
                return FileSlice(
                    path=path, offset=offset, limit=limit,
                    actual_lines=0, content=f"[Error reading file: {e}]",
                )

        if total_lines is None:
            total_lines = len(lines)

        # 计算实际读取范围
        ctx_start = max(0, offset - context_lines - 1)
        read_end = min(total_lines, offset + limit - 1 + context_lines)

        selected = lines[ctx_start:read_end]
        actual = len(selected)

        # 标记截断
        truncated = (offset + limit - 1) < total_lines

        # 构建内容（带行号）
        numbered_lines: list[str] = []
        for i, line in enumerate(selected, ctx_start + 1):
            prefix = ">>>" if offset <= i < offset + limit else "   "
            numbered_lines.append(f"{prefix} {i:5d} | {line}")

        header = f"# File: {path} (lines {offset}-{min(offset + limit - 1, total_lines)} / {total_lines})"
        if truncated:
            header += " [truncated]"

        content = header + "\n" + "-" * 60 + "\n" + "\n".join(numbered_lines)

        return FileSlice(
            path=path,
            offset=offset,
            limit=limit,
            actual_lines=actual,
            content=content,
            total_lines=total_lines,
            truncated=truncated,
        )

    # ── P1: 目录树 ────────────────────────────────────

    def list_files(
        self,
        path: str = ".",
        max_depth: int = 3,
        respect_ignore: bool = True,
        include_stats: bool = True,
    ) -> FileNode:
        """
        列出目录结构树。

        Args:
            path: 起始路径
            max_depth: 最大递归深度
            respect_ignore: 遵守忽略规则
            include_stats: 包含文件大小和行数

        Returns:
            FileNode 树根节点
        """
        abs_path = os.path.abspath(self._resolve_path(path))

        if os.path.isfile(abs_path):
            return self._file_node(abs_path, ".", include_stats)

        root_node = FileNode(
            name=os.path.basename(abs_path) or ".",
            path=path,
            is_dir=True,
        )

        self._walk_dir(abs_path, root_node, 0, max_depth, respect_ignore, include_stats)
        return root_node

    def _walk_dir(
        self,
        abs_dir: str,
        parent: FileNode,
        depth: int,
        max_depth: int,
        respect_ignore: bool,
        include_stats: bool,
    ) -> None:
        if depth >= max_depth:
            return

        try:
            entries = sorted(os.listdir(abs_dir))
        except OSError:
            return

        for entry in entries:
            full = os.path.join(abs_dir, entry)
            rel = os.path.relpath(full, self.root)

            if respect_ignore and self._ignore.is_ignored(rel):
                continue

            if os.path.isdir(full):
                child = FileNode(name=entry, path=rel, is_dir=True)
                self._walk_dir(full, child, depth + 1, max_depth, respect_ignore, include_stats)
                if child.children:  # 只添加非空目录
                    parent.children.append(child)
            else:
                parent.children.append(self._file_node(full, rel, include_stats))

    def _file_node(self, abs_path: str, rel_path: str, include_stats: bool) -> FileNode:
        node = FileNode(
            name=os.path.basename(abs_path),
            path=rel_path,
            is_dir=False,
        )
        if include_stats:
            try:
                node.size_bytes = os.path.getsize(abs_path)
                mime, _ = mimetypes.guess_type(abs_path)
                node.mime_type = mime or ""
                # 快速统计行数（前1KB采样）
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                        sample = f.read(1024)
                        if len(sample) < 1024:
                            # 小文件：精确计数
                            node.total_lines = sample.count("\n") + (1 if sample and not sample.endswith("\n") else 0)
                        else:
                            # 大文件：估算
                            line_count_sample = sample.count("\n")
                            avg_line = 1024 / max(line_count_sample, 1)
                            node.total_lines = int(node.size_bytes / avg_line)
                except Exception:
                    pass
            except OSError:
                pass
        return node

    # ── P2: 文件摘要 ──────────────────────────────────

    def file_summary(
        self,
        path: str,
        max_head_lines: int = 20,
        max_tail_lines: int = 10,
    ) -> FileSummary:
        """
        生成文件摘要（不读取全文）。

        对代码文件提取：导入、类定义、函数签名
        对文本文件提取：首尾内容
        """
        abs_path = os.path.abspath(self._resolve_path(path))

        try:
            size = os.path.getsize(abs_path)
        except OSError as e:
            return FileSummary(path=path, mime_type="", size_bytes=0, total_lines=0)

        mime, _ = mimetypes.guess_type(abs_path)
        ext = os.path.splitext(path)[1].lower()

        # 读取文件
        cached = self._cache.get(abs_path)
        if cached:
            content, total_lines = cached
            lines = content.splitlines()
        else:
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    lines = content.splitlines()
                    total_lines = len(lines)
                    if size <= self.MAX_FILE_SIZE:
                        self._cache.put(abs_path, content, total_lines)
            except Exception:
                return FileSummary(path=path, mime_type=mime or "", size_bytes=size, total_lines=0)

        summary = FileSummary(
            path=path,
            mime_type=mime or "",
            size_bytes=size,
            total_lines=total_lines,
            head_lines=lines[:max_head_lines],
            tail_lines=lines[-max_tail_lines:] if total_lines > max_tail_lines else [],
        )

        # 代码文件：提取结构信息
        if ext in self.CODE_EXTENSIONS:
            summary.imports = self._extract_imports(lines, ext)
            summary.classes = self._extract_classes(lines, ext)
            summary.functions = self._extract_functions(lines, ext)

        return summary

    def _extract_imports(self, lines: list[str], ext: str) -> list[str]:
        """提取导入语句。"""
        imports: list[str] = []
        if ext == ".py":
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    imports.append(stripped)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(("import ", "require(", "export ")):
                    imports.append(stripped)
        elif ext in (".java", ".kt"):
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("import "):
                    imports.append(stripped)
        elif ext == ".go":
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("import "):
                    imports.append(stripped)
        return imports[:30]  # 最多 30 条

    def _extract_classes(self, lines: list[str], ext: str) -> list[str]:
        """提取类定义。"""
        classes: list[str] = []
        if ext == ".py":
            for line in lines:
                m = re.match(r"^\s*class\s+(\w+)", line)
                if m:
                    classes.append(f"class {m.group(1)}")
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            for line in lines:
                m = re.match(r"^\s*class\s+(\w+)", line)
                if m:
                    classes.append(f"class {m.group(1)}")
                m = re.match(r"^\s*interface\s+(\w+)", line)
                if m:
                    classes.append(f"interface {m.group(1)}")
        elif ext in (".java", ".kt"):
            for line in lines:
                m = re.match(r"^\s*(?:public\s+|private\s+|protected\s+)?(?:abstract\s+)?class\s+(\w+)", line)
                if m:
                    classes.append(f"class {m.group(1)}")
        return classes[:20]

    def _extract_functions(self, lines: list[str], ext: str) -> list[str]:
        """提取函数/方法签名。"""
        funcs: list[str] = []
        if ext == ".py":
            for line in lines:
                m = re.match(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", line)
                if m and m.group(1) not in ("__init__",):
                    funcs.append(f"def {m.group(1)}(...)")
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            for line in lines:
                m = re.match(r"^\s*(?:async\s+)?(?:function\s+(\w+)|(\w+)\s*[:=]\s*(?:async\s+)?\(|const\s+(\w+)\s*=\s*(?:async\s+)?\()")
                if m:
                    name = m.group(1) or m.group(2) or m.group(3)
                    if name:
                        funcs.append(f"function {name}(...)")
        elif ext in (".java", ".kt"):
            for line in lines:
                m = re.match(r"^\s*(?:public\s+|private\s+|protected\s+)?(?:static\s+)?[\w<>\[\]]+\s+(\w+)\s*\(", line)
                if m:
                    funcs.append(f"{m.group(1)}(...)")
        return funcs[:30]

    # ── 组合操作 ──────────────────────────────────────

    def search_with_context(
        self,
        pattern: str,
        path: str = ".",
        read_context_lines: int = 15,
        **search_kw: Any,
    ) -> list[dict[str, Any]]:
        """
        搜索 + 自动读取匹配点上下文。

        返回: [{"search": SearchResult, "slice": FileSlice}, ...]
        """
        results = self.search_code(pattern, path=path, **search_kw)
        enriched: list[dict[str, Any]] = []

        for sr in results:
            fslice = self.read_file_range(
                sr.path,
                offset=max(1, sr.line_number - read_context_lines // 2),
                limit=read_context_lines,
            )
            enriched.append({"search": sr, "slice": fslice})

        return enriched

    # ── 写入操作 ───────────────────────────────────────

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        """写入文件，自动创建父目录，旧版本存档到 versions/ 子目录，返回 {success, bytes, error}。"""
        try:
            full = self._resolve_path(path)
            os.makedirs(os.path.dirname(full) or ".", exist_ok=True)

            # 若文件已存在，备份旧版本到 versions/{timestamp}/ 子目录
            if os.path.exists(full):
                import shutil
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                versions_dir = os.path.join(
                    os.path.dirname(full) or self.root, "versions", timestamp
                )
                os.makedirs(versions_dir, exist_ok=True)
                backup_name = os.path.join(versions_dir, os.path.basename(full))
                # 避免冲突：若同名备份已存在，追加微秒
                if os.path.exists(backup_name):
                    backup_name = (
                        f"{backup_name}.{int(time.time() * 1000) % 1000}"
                    )
                shutil.copy2(full, backup_name)

            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            self._invalidate_cache(path)
            return {"success": True, "bytes": len(content.encode("utf-8"))}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def make_dir(self, path: str) -> dict[str, Any]:
        """创建目录（递归），返回 {success, error}。"""
        try:
            full = self._resolve_path(path)
            os.makedirs(full, exist_ok=True)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── 统计 ──────────────────────────────────────────

    @property
    def cache_stats(self) -> dict[str, Any]:
        return {
            "cache_size": self._cache.size,
            "total_reads": self._total_reads,
            "cache_hits": self._cache_hits,
            "hit_rate": f"{self._cache_hits / max(self._total_reads, 1) * 100:.1f}%",
        }

    def clear_cache(self) -> None:
        self._cache.clear()
