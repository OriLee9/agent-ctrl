#!/usr/bin/env python3
"""
Agent Workflow Framework — 统一启动入口。

一键启动：后端 Flask API + 前端 Vite Dev Server + 可选的演示模式。

用法:
    python launch.py              # 默认模式（API + frontend dev）
    python launch.py --api-only   # 仅启动 API 服务
    python launch.py --demo       # 启动演示模式（含模拟 Agent 运行）
    python launch.py --port 8080  # 自定义 API 端口

环境变量 (.env):
    DEEPSEEK_API_KEY=sk-xxx       # DeepSeek API Key
    API_PORT=5000                 # Flask API 端口
    FRONTEND_PORT=5173            # Vite Dev Server 端口
    API_HOST=0.0.0.0              # API 监听地址
    DEMO_MODE=false               # 是否启用演示模式
    DB_PATH=/tmp/agent_workflow/context_hub.db  # SQLite 路径
    CHECKPOINT_DIR=/tmp/agent_workflow/checkpoints  # Checkpoint 目录

热修改支持:
    - 修改前端代码 → Vite HMR 自动刷新
    - 修改后端 Python → 保存后自动生效（Flask threaded 模式）
    - 修改 .env → 需要重启 launch.py
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# 框架根目录
FRAMEWORK_DIR = Path(__file__).parent.resolve()
APP_DIR = FRAMEWORK_DIR.parent / "app"

# 加载 .env
def load_env() -> None:
    """从 .env 文件加载环境变量。"""
    env_file = FRAMEWORK_DIR / ".env"
    if env_file.exists():
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    # 只在未设置时才覆盖
                    if key and key not in os.environ:
                        os.environ[key] = value.strip().strip('"\'')


load_env()

# ── 参数解析 ──────────────────────────────────────────────

parser = argparse.ArgumentParser(
    description="Agent Workflow Framework — Unified Launcher",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
示例:
  %(prog)s                    启动 API + Frontend dev server
  %(prog)s --demo             启动演示模式（模拟 Agent 运行）
  %(prog)s --api-only         仅启动 API
  %(prog)s --build            构建前端生产包
  %(prog)s --api-port 8080    自定义 API 端口
    """,
)
parser.add_argument("--api-only", action="store_true", help="仅启动 Flask API")
parser.add_argument("--demo", action="store_true", help="演示模式（含模拟 Agent）")
parser.add_argument("--build", action="store_true", help="构建前端生产包")
parser.add_argument("--api-port", type=int, default=int(os.environ.get("API_PORT", "5000")), help="API 端口")
parser.add_argument("--api-host", default=os.environ.get("API_HOST", "0.0.0.0"), help="API 监听地址")
parser.add_argument("--frontend-port", type=int, default=int(os.environ.get("FRONTEND_PORT", "5173")), help="前端端口")
args = parser.parse_args()


# ── 子进程启动器 ──────────────────────────────────────────

def start_api_server(host: str, port: int, demo: bool = False) -> subprocess.Popen:
    """启动 Flask API 服务。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(FRAMEWORK_DIR)

    if demo:
        cmd = [sys.executable, "-m", "examples.demo_server"]
    else:
        cmd = [sys.executable, "-m", "api_server"]

    print(f"[API ] Starting on {host}:{port} {'(demo)' if demo else ''}")
    return subprocess.Popen(
        cmd,
        cwd=FRAMEWORK_DIR,
        env=env,
    )


def start_frontend_dev(port: int) -> subprocess.Popen | None:
    """启动 Vite Dev Server。"""
    if not APP_DIR.exists():
        print(f"[WARN] Frontend dir not found: {APP_DIR}")
        return None

    # 查找 npm 完整路径（Windows 上 subprocess.Popen 不继承 shell PATH）
    npm = shutil.which("npm")
    if npm is None:
        print("[WARN] npm not found in PATH — frontend will not start")
        print("       Install Node.js or use: python launch.py --api-only")
        return None

    # 检查 node_modules
    if not (APP_DIR / "node_modules").exists():
        print("[FE  ] Installing dependencies...")
        result = subprocess.run(
            [npm, "install"],
            cwd=APP_DIR,
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"[WARN] npm install failed: {result.stderr.decode()[:200]}")

    print(f"[FE  ] Starting dev server on port {port}")
    return subprocess.Popen(
        [npm, "run", "dev", "--", "--port", str(port)],
        cwd=APP_DIR,
    )


def build_frontend() -> bool:
    """构建前端生产包。"""
    if not APP_DIR.exists():
        print(f"[ERR ] Frontend dir not found: {APP_DIR}")
        return False

    npm = shutil.which("npm")
    if npm is None:
        print("[ERR ] npm not found in PATH")
        return False

    print("[FE  ] Building production bundle...")
    result = subprocess.run(
        [npm, "run", "build"],
        cwd=APP_DIR,
    )
    if result.returncode == 0:
        print(f"[FE  ] Build OK → {APP_DIR / 'dist'}")
        return True
    else:
        print("[ERR ] Build failed")
        return False


# ── 主流程 ────────────────────────────────────────────────

def main() -> None:
    # 构建模式
    if args.build:
        build_frontend()
        return

    processes: list[subprocess.Popen] = []

    try:
        # 1. 启动 API
        api_proc = start_api_server(args.api_host, args.api_port, demo=args.demo)
        processes.append(api_proc)
        time.sleep(1)  # 给 API 启动时间

        if api_proc.poll() is not None:
            print("[ERR ] API server failed to start")
            return

        # 2. 启动前端（非 --api-only 模式）
        if not args.api_only:
            fe_proc = start_frontend_dev(args.frontend_port)
            if fe_proc:
                processes.append(fe_proc)

        # 3. 打印信息
        print("\n" + "=" * 60)
        if args.demo:
            print("Agent Workflow Framework — DEMO MODE")
        else:
            print("Agent Workflow Framework")
        print("=" * 60)
        print(f"API:     http://{args.api_host}:{args.api_port}")
        if not args.api_only:
            print(f"Frontend: http://localhost:{args.frontend_port}")
        if args.demo:
            print("\n演示模式: 包含模拟 Agent 产生实时事件")
        print("\n热修改:")
        print("  - 前端代码修改 → Vite HMR 自动刷新")
        print("  - .env 修改    → 需重启 launch.py")
        print("\n按 Ctrl+C 停止\n")

        # 4. 等待
        while True:
            for p in processes:
                ret = p.poll()
                if ret is not None:
                    print(f"\n[WARN] Process exited with code {ret}")
                    return
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\n[STOP] Shutting down...")
    finally:
        for p in processes:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        print("[STOP] All processes stopped")


if __name__ == "__main__":
    main()
