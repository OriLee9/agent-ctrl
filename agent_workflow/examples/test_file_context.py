"""
FileContextManager 完整测试。

覆盖:
P0: search_code, read_file_range
P1: list_files, .agentignore
P2: file_summary, cache
集成: FileTools @tool 注册
"""
from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.file_context import FileContextManager, FileCache, IgnoreRuleManager
from core.file_tools import FileTools
from core.agent import Agent, AgentConfig
from core.llm import BaseLLM, LLMResponse, ToolCall, Usage
from core.tool import done

PASS = 0
FAIL = 0


def check(desc: str, cond: bool):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS: {desc}")
    else:
        FAIL += 1
        print(f"  FAIL: {desc}")


# ── 创建测试项目结构 ──────────────────────────────

def create_test_project() -> str:
    tmp = tempfile.mkdtemp(prefix="test_project_")

    # src/main.py — 中等大小
    main_py = '''#!/usr/bin/env python3
"""Main application module."""

import os
import sys
import json
from typing import Dict, List, Optional
from dataclasses import dataclass

from utils.helpers import format_name, validate_email
from models.user import User, UserManager
from config.settings import DEBUG, DATABASE_URL


@dataclass
class AppConfig:
    """Application configuration."""
    name: str
    version: str
    debug: bool = False
    port: int = 8080


class Application:
    """Main application class."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.users: Dict[str, User] = {}
        self._running = False
        self._server = None

    def start(self) -> None:
        """Start the application server."""
        self._running = True
        self._setup_routes()
        self._connect_database()
        print(f"Starting {self.config.name} v{self.config.version}")

    def stop(self) -> None:
        """Stop the application."""
        self._running = False
        if self._server:
            self._server.close()

    def _setup_routes(self) -> None:
        """Configure URL routes."""
        routes = [
            ("/", self.handle_index),
            ("/users", self.handle_users),
            ("/users/<id>", self.handle_user_detail),
        ]

    def _connect_database(self) -> None:
        """Establish database connection."""
        pass

    def handle_index(self, request: Dict) -> Dict:
        """Handle GET /."""
        return {"status": "ok", "version": self.config.version}

    def handle_users(self, request: Dict) -> List[Dict]:
        """Handle GET /users."""
        return [u.to_dict() for u in self.users.values()]

    def handle_user_detail(self, request: Dict, user_id: str) -> Optional[Dict]:
        """Handle GET /users/<id>."""
        user = self.users.get(user_id)
        return user.to_dict() if user else None

    async def process_async(self, data: str) -> str:
        """Async data processing."""
        await self._validate(data)
        return f"processed: {data}"

    async def _validate(self, data: str) -> bool:
        """Validate input data."""
        return len(data) > 0


def main():
    config = AppConfig(name="MyApp", version="1.0.0", debug=True)
    app = Application(config)
    app.start()


if __name__ == "__main__":
    main()
'''

    # src/models/user.py
    user_py = '''"""User model definitions."""

from dataclasses import dataclass, field
from typing import Optional
import hashlib
import uuid

from utils.validators import validate_email


@dataclass
class User:
    """User entity."""
    id: str
    name: str
    email: str
    active: bool = True
    roles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "active": self.active,
        }

    def deactivate(self) -> None:
        self.active = False

    def has_role(self, role: str) -> bool:
        return role in self.roles


class UserManager:
    """Manages user CRUD operations."""

    def __init__(self):
        self._users: dict[str, User] = {}
        self._index_by_email: dict[str, str] = {}

    def create(self, name: str, email: str) -> User:
        user_id = str(uuid.uuid4())
        user = User(id=user_id, name=name, email=email)
        self._users[user_id] = user
        self._index_by_email[email] = user_id
        return user

    def get_by_id(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def get_by_email(self, email: str) -> Optional[User]:
        uid = self._index_by_email.get(email)
        return self._users.get(uid) if uid else None

    def list_all(self) -> list[User]:
        return list(self._users.values())

    def delete(self, user_id: str) -> bool:
        user = self._users.pop(user_id, None)
        if user:
            self._index_by_email.pop(user.email, None)
            return True
        return False
'''

    # src/utils/helpers.py
    helpers_py = '''"""Utility helper functions."""

import re
import datetime
from typing import Optional


def format_name(first: str, last: str) -> str:
    """Format full name."""
    return f"{first.strip()} {last.strip()}".title()


def validate_email(email: str) -> bool:
    """Validate email format."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def parse_date(date_str: str) -> Optional[datetime.datetime]:
    """Parse date string."""
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y"]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def slugify(text: str) -> str:
    """Convert text to URL slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\\w\\s-]", "", text)
    text = re.sub(r"[\\s]+", "-", text)
    return text[:50]
'''

    # README.md
    readme_md = """# Test Project

A sample Python project for testing file context manager.

## Structure

- src/main.py — Application entry
- src/models/ — Data models
- src/utils/ — Helper functions

## Usage

```python
from main import Application, AppConfig
config = AppConfig(name="test", version="0.1")
app = Application(config)
app.start()
```

## TODO
- Add authentication
- Add logging middleware
- Optimize database queries
"""

    # config/settings.py
    settings_py = """# Application settings

import os

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

# Server settings
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "8080"))
WORKERS = int(os.getenv("WORKERS", "4"))

# Feature flags
ENABLE_CACHE = True
ENABLE_METRICS = False
"""

    # package.json (应被忽略规则排除或标记为非代码)
    pkg_json = """{"name": "test", "version": "1.0.0"}"""

    # .agentignore
    agentignore = """# Agent ignore rules
*.log
coverage/
"""

    # tests/test_main.py
    test_py = '''"""Tests for main module."""

import pytest
from src.main import Application, AppConfig


class TestApplication:
    def test_create_app(self):
        config = AppConfig(name="test", version="0.1")
        app = Application(config)
        assert app.config.name == "test"

    def test_start_stop(self):
        config = AppConfig(name="test", version="0.1")
        app = Application(config)
        app.start()
        assert app._running is True
        app.stop()
        assert app._running is False
'''

    # large_file.py — 模拟超大文件（500行）
    large_lines = ['# Large generated file\n']
    for i in range(1, 500):
        large_lines.append(f'def function_{i}(x, y):\n    return x + y + {i}\n')
    large_py = ''.join(large_lines)

    # 写入所有文件
    files = {
        "src/main.py": main_py,
        "src/models/user.py": user_py,
        "src/utils/helpers.py": helpers_py,
        "config/settings.py": settings_py,
        "README.md": readme_md,
        "package.json": pkg_json,
        ".agentignore": agentignore,
        "tests/test_main.py": test_py,
        "src/large_file.py": large_py,
    }

    for relpath, content in files.items():
        full = os.path.join(tmp, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)

    return tmp


# ═══════════════════════════════════════════════════════════════
# 测试 1: search_code — 搜索功能
# ═══════════════════════════════════════════════════════════════

def test_search_code(ctx: FileContextManager):
    print("\n[TEST 1] search_code")

    # 1a: 基本搜索
    results = ctx.search_code("class User", path="src")
    check("Found User class", len(results) >= 1)
    if results:
        check("Correct file", results[0].path == "src/models/user.py")
        check("Has line number", results[0].line_number > 0)

    # 1b: 搜索特定方法
    results = ctx.search_code("def handle_users", path="src")
    check("Found handle_users", len(results) >= 1)
    results = ctx.search_code("def handle_index", path="src")
    check("Found handle_index", len(results) >= 1)

    # 1c: 类型过滤
    results = ctx.search_code("def ", path=".", file_type=".py", max_results=10)
    check("Filtered by .py", all(r.path.endswith(".py") for r in results))

    # 1d: 大小写不敏感
    results = ctx.search_code("APPLICATION", path="src")
    check("Case insensitive", len(results) >= 1)

    # 1e: 无结果
    results = ctx.search_code("xyz_nonexistent_12345")
    check("No results for nonsense", len(results) == 0)


# ═══════════════════════════════════════════════════════════════
# 测试 2: read_file_range — 分段读取
# ═══════════════════════════════════════════════════════════════

def test_read_file_range(ctx: FileContextManager):
    print("\n[TEST 2] read_file_range")

    # 2a: 基本读取
    fslice = ctx.read_file_range("src/main.py", offset=1, limit=10)
    check("Read 10 lines", fslice.actual_lines >= 10)
    check("Contains header", "File: src/main.py" in fslice.content)
    check("Has line numbers", "1 |" in fslice.content)

    # 2b: 精确范围
    fslice = ctx.read_file_range("src/main.py", offset=25, limit=5)
    check("Offset 25", "25 |" in fslice.content)
    check("Limit 5 lines", ">>>" in fslice.content)

    # 2c: 超大文件分段 — 只读一小部分
    fslice = ctx.read_file_range("src/large_file.py", offset=200, limit=10)
    check("Large file partial read", fslice.actual_lines == 10)
    check("Truncated flag", fslice.truncated is True)
    check("Total lines approx 500", fslice.total_lines is not None and fslice.total_lines >= 400)

    # 2d: 超出范围
    fslice = ctx.read_file_range("src/main.py", offset=9999, limit=10)
    check("Out of range safe", fslice.actual_lines == 0 or "lines" in fslice.content)

    # 2e: 不存在的文件
    fslice = ctx.read_file_range("nonexistent.py")
    check("Missing file error", "Error" in fslice.content)


# ═══════════════════════════════════════════════════════════════
# 测试 3: list_files — 目录树
# ═══════════════════════════════════════════════════════════════

def test_list_files(ctx: FileContextManager):
    print("\n[TEST 3] list_files")

    root = ctx.list_files(".", max_depth=3)
    check("Root is dir", root.is_dir)

    names = [c.name for c in root.children]
    check("Has src/", "src" in names or any("src" in c.path for c in root.children))

    # 递归到 src
    src_node = next((c for c in root.children if c.name == "src"), None)
    if src_node:
        check("src has children", len(src_node.children) > 0)

    # 文件元数据
    all_files = []
    def collect(n):
        if not n.is_dir:
            all_files.append(n)
        for c in n.children:
            collect(c)
    collect(root)

    py_files = [f for f in all_files if f.name.endswith(".py")]
    check("Found Python files", len(py_files) > 0)
    if py_files:
        check("Has size info", py_files[0].size_bytes > 0)


# ═══════════════════════════════════════════════════════════════
# 测试 4: file_summary — 文件摘要
# ═══════════════════════════════════════════════════════════════

def test_file_summary(ctx: FileContextManager):
    print("\n[TEST 4] file_summary")

    summary = ctx.file_summary("src/main.py")
    check("Has mime type", summary.mime_type != "")
    check("Has total lines", summary.total_lines > 30)
    check("Found imports", len(summary.imports) >= 5)
    check("Found classes", len(summary.classes) >= 2)  # AppConfig, Application
    check("Found functions", len(summary.functions) >= 3)
    check("Has head lines", len(summary.head_lines) > 0)

    # user.py
    summary = ctx.file_summary("src/models/user.py")
    check("User classes", any("User" in c for c in summary.classes))
    check("User functions", len(summary.functions) >= 3)


# ═══════════════════════════════════════════════════════════════
# 测试 5: search_with_context — 搜索+上下文
# ═══════════════════════════════════════════════════════════════

def test_search_with_context(ctx: FileContextManager):
    print("\n[TEST 5] search_with_context")

    enriched = ctx.search_with_context("class UserManager", path="src")
    check("Found match", len(enriched) >= 1)
    if enriched:
        check("Has slice", "File:" in enriched[0]["slice"].content)
        check("Slice has content", enriched[0]["slice"].actual_lines > 0)


# ═══════════════════════════════════════════════════════════════
# 测试 6: cache — LRU 缓存
# ═══════════════════════════════════════════════════════════════

def test_cache(ctx: FileContextManager):
    print("\n[TEST 6] File cache")

    # 首次读取小文件（触发缓存）
    ctx.read_file_range("config/settings.py", offset=1, limit=5)
    stats1 = ctx.cache_stats
    check("Cache has entry after read", stats1["cache_size"] >= 1)

    # 再次读取不同范围（应命中缓存）
    hits_before = stats1["cache_hits"]
    ctx.read_file_range("config/settings.py", offset=3, limit=5)
    stats2 = ctx.cache_stats
    check("Cache hit on second read", stats2["cache_hits"] > hits_before)

    # 清除
    ctx.clear_cache()
    check("Cache cleared", ctx.cache_stats["cache_size"] == 0)


# ═══════════════════════════════════════════════════════════════
# 测试 7: ignore 规则 — .agentignore
# ═══════════════════════════════════════════════════════════════

def test_ignore(ctx: FileContextManager, tmpdir: str):
    print("\n[TEST 7] Ignore rules")

    # 创建应被忽略的文件（coverage/ 目录下，非 .log 后缀）
    cov_dir = os.path.join(tmpdir, "coverage")
    os.makedirs(cov_dir, exist_ok=True)
    with open(os.path.join(cov_dir, "stats.txt"), "w") as f:
        f.write("COVERAGE_SECRET\n")

    # 搜索不应找到 coverage/ 下的内容
    results = ctx.search_code("COVERAGE_SECRET", path=".")
    check(".agentignore excludes coverage/", len(results) == 0)

    # 内置排除: node_modules
    check("Built-in ignore", ctx._ignore.is_ignored("node_modules/package.json"))
    check("Built-in ignore __pycache__", ctx._ignore.is_ignored("__pycache__/foo.py"))


# ═══════════════════════════════════════════════════════════════
# 测试 8: FileTools — @tool 集成
# ═══════════════════════════════════════════════════════════════

class QuickMockLLM(BaseLLM):
    def model_id(self): return "mock"
    def chat(self, messages, tools=None, temperature=None, stream_callback=None):
        return LLMResponse(
            content="Done",
            tool_calls=[ToolCall(id="c", function="done", arguments='{"result": "ok"}')],
            usage=Usage(1, 1, 2),
        )


def test_file_tools(tmpdir: str):
    print("\n[TEST 8] FileTools @tool integration")

    ft = FileTools(root=tmpdir)
    tools = ft.get_tools()
    check("5 tools registered", len(tools) == 5)

    # 工具名检查
    names = [t.name for t in tools]
    check("has search_code", "search_code" in names)
    check("has read_file_range", "read_file_range" in names)
    check("has list_files", "list_files" in names)
    check("has file_summary", "file_summary" in names)
    check("has search_with_context", "search_with_context" in names)

    # 实际调用
    search_tool = next(t for t in tools if t.name == "search_code")
    result = search_tool.execute(pattern="class Application", path="src")
    result_text = result.to_text()
    check("Tool found Application", "Application" in result_text)
    check("Tool returns file path", "src/main.py" in result_text)

    # Agent 集成
    agent = Agent(llm=QuickMockLLM(), tools=tools + [done])
    check("Agent has file tools", len(agent.list_tools()) >= 5)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("FileContextManager 测试")
    print("=" * 60)

    tmpdir = create_test_project()
    print(f"\nTest project: {tmpdir}")

    ctx = FileContextManager(root=tmpdir, cache_size=10)

    test_search_code(ctx)
    test_read_file_range(ctx)
    test_list_files(ctx)
    test_file_summary(ctx)
    test_search_with_context(ctx)
    test_cache(ctx)
    test_ignore(ctx, tmpdir)
    test_file_tools(tmpdir)

    # 清理
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果: {PASS} 通过, {FAIL} 失败")
    print("=" * 60)

    if FAIL > 0:
        sys.exit(1)