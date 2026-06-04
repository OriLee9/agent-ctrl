# Agent Workflow Framework

> **奥卡姆剃刀原则** — 简洁、可复用、拒绝冗余代码。
> 一个从零构建的 Python Agent Workflow 框架，支持多 Agent 协作、DAG 工作流编排、Review Gate 自动返工、Human-in-the-loop 审批、断点续跑、Register-Memory 对话压缩、超长上下文文件管理。

---

## 项目结构

```
agent_workflow/                 # 后端框架
├── core/                       # 核心层
│   ├── llm.py                  # LLM 抽象（DeepSeek / OpenAI）
│   ├── agent.py                # ReAct 循环（Thought → Action → Observation）
│   ├── tool.py                 # @tool 装饰器（自动 JSON Schema 推断）
│   ├── memory.py               # Conversation + Snapshot + Observer + archive_round + compact
│   ├── file_context.py         # 超大文件管理（检索/分段读取/缓存/版本化写入）
│   ├── file_tools.py           # 文件操作 @tool 集合（write_file / read_file_range / search_code / ...）
│   ├── review_tools.py         # 结构化评审工具（review_decision）
│   ├── skill.py                # Skill 注册管理
│   └── sub_agent.py            # 子 Agent 委派
├── orchestration/              # 编排层
│   ├── context_hub.py          # 中心化上下文监控（v3.0 纯监控用途）
│   ├── task.py                 # Task 定义（模板变量）
│   ├── rules.py                # 规则引擎（重复短句检测 → 自动打断）
│   ├── workflow.py             # 向后兼容别名
│   └── workflow/               # 合并后的工作流模块
│       ├── engine.py           # WorkflowEngine（DAG + V2 生产特性 + Review Gate）
│       ├── state.py            # 状态机（WorkflowState / TaskState）
│       ├── checkpoint.py       # 断点续跑（JSON 序列化）
│       └── presets.py          # 预设构造器（顺序/并行/MapReduce/条件）
├── api_server.py               # Flask API（前端数据后端）
├── launch.py                   # 统一启动入口
├── .env.example                # 配置模板
├── utils/                      # 工具模块
│   ├── logging_config.py       # 日志配置
│   └── report.py               # 运行报告生成
├── validation/                 # 验证模块
│   ├── runner.py               # 验证运行器
│   └── validators.py           # 验证规则
└── examples/                   # 示例与测试

app/                            # 前端监控面板
├── src/
│   ├── components/             # React 组件
│   │   ├── StatusBar.tsx       # 顶部状态栏
│   │   ├── AgentSidebar.tsx    # Agent 列表
│   │   ├── AgentDetail.tsx     # Agent 详情（消息/步骤/快照）
│   │   ├── MessageFlow.tsx     # 消息流可视化（支持 Round 分组）
│   │   ├── WorkflowDAG.tsx     # 工作流 DAG 可视化（含 Review Gate 边）
│   │   ├── WorkflowBuilder.tsx # 工作流构建器
│   │   ├── WorkflowLauncher.tsx# 工作流启动器
│   │   ├── WorkflowControl.tsx # Workflow 控制（暂停/恢复/终止/审批）
│   │   ├── DemoTemplates.tsx   # Demo 模板面板（赛车/Snake）
│   │   ├── ArtifactsPanel.tsx  # 产物面板（文件预览/下载）
│   │   ├── InterventionPanel.tsx # 干预面板
│   │   ├── EventLog.tsx        # 实时事件日志
│   │   └── HelpPanel.tsx       # 帮助面板
│   ├── hooks/useApi.ts         # API 请求 Hook
│   ├── types/index.ts          # TypeScript 类型定义
│   └── App.tsx                 # 主应用
├── package.json
└── vite.config.ts
```

---

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Agent Workflow                        │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │   LLM    │  │  Agent   │  │   Tool   │  │  Memory  │  │
│  │ (DeepSeek│  │ (ReAct   │  │(@tool   │  │(Conversa-│  │
│  │ /OpenAI) │  │  Loop)   │  │decorator│  │  tion)   │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │             │             │             │         │
│  ┌────▼─────────────▼─────────────▼─────────────▼─────┐  │
│  │              Orchestration Layer                    │  │
│  │  ┌──────────────┐  ┌──────────────────────────┐   │  │
│  │  │  ContextHub  │  │    WorkflowEngine         │   │  │
│  │  │  (Monitor)   │  │  ┌────┐  ┌──────────┐   │   │  │
│  │  │  ┌────────┐  │  │  │DAG │  │Checkpoint│   │   │  │
│  │  │  │Observer│  │  │  │Topo│  │Resume    │   │   │  │
│  │  │  │SQLite  │  │  │  │Sort│  │ReviewGate│   │   │  │
│  │  │  │Persis.│  │  │  │Cond.│  │Approval  │   │   │  │
│  │  │  └────────┘  │  │  │Edge │  │Retry     │   │   │  │
│  │  └──────────────┘  │  └────┘  └──────────┘   │   │  │
│  └────────────────────┬────────────────────────────┘  │
│                       │                                  │
│  ┌────────────────────▼────────────────────────────┐  │
│  │           FileContextManager                     │  │
│  │  search_code() | read_file_range() | write_file()│  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 1. 环境准备

```bash
# 安装 Python 依赖
pip install -r requirements.txt
# 或包含开发依赖
pip install -r requirements-dev.txt

# 前端依赖（已预装，如缺失则执行）
cd app && npm install
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key
```

示例 `.env`：

```bash
DEEPSEEK_API_KEY=sk-your-api-key-here
API_PORT=5000
FRONTEND_PORT=5173
API_HOST=0.0.0.0
AGENT_OUTPUTS_DIR=/tmp/agent_workflow/outputs
```

### 3. 一键启动

```bash
# 启动 API + 前端 Dev Server
python agent_workflow/launch.py

# 访问 http://localhost:5173 查看监控面板
# API 端点: http://localhost:5000

# 仅启动 API
python agent_workflow/launch.py --api-only

# 演示模式（含模拟 Agent 实时事件）
python agent_workflow/launch.py --demo

# 自定义端口
python agent_workflow/launch.py --port 8080
```

### 4. 第一个 Agent

```python
from core.llm import DeepSeekLLM
from core.agent import Agent, AgentConfig
from core.tool import tool, done

# 1. 创建 LLM
llm = DeepSeekLLM(api_key="sk-xxx")

# 2. 定义工具
@tool
def search(query: str) -> str:
    """Search the web."""
    return f"Results for: {query}"

# 3. 创建 Agent
agent = Agent(
    llm=llm,
    tools=[search, done],
    config=AgentConfig(max_iterations=10),
)

# 4. 运行
result = agent.run("Research AI frameworks")
print(result.output)
```

---

## 核心概念

### Agent — ReAct 循环

```python
result = agent.run(task, stream_callback=on_token)
# Thought → Action (Tool) → Observation → ... → done()
```

配置选项：

| 参数 | 说明 |
| ---- | ---- |
| `max_iterations` | 最大 ReAct 步数 |
| `temperature` | LLM 采样温度（0-2） |
| `budget_tokens` | Token 预算上限（0=无限制） |
| `checkpoint_enabled` | 步级 checkpoint 持久化 |
| `allowed_tools` | 允许使用的工具白名单 |

### @tool — 自动 Schema 推断

```python
@tool
def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """Write a file."""
    Args:
        path: File path
        content: File content
        overwrite: Whether to overwrite existing file
    """
    ...
# 自动生成 JSON Schema，LLM 可直接调用
```

### Skill — 可复用能力包

将 system_prompt + tools 打包为可复用的 Skill，不同 Agent 加载不同能力：

```python
from core.skill import Skill, SkillRegistry

registry = SkillRegistry()

# 注册设计能力
registry.register(Skill(
    name="design",
    description="Design document generation",
    system_prompt="You are an architecture designer...",
    tools=[search_code, read_file_range],
))

# 注册编码能力
registry.register(Skill(
    name="coding",
    description="Code generation",
    system_prompt="You are an expert programmer...",
    tools=[write_file, search_code],
    parameters={"language": "python"},
))

# 应用到 Agent
agent = Agent(llm=llm)
registry.apply_to_agent("coding", agent, language="Rust")

# 组合多个 Skill
combined = registry.combine(["research", "coding"])
```

### 本地工具执行 — run_command

Agent 可直接调用本地 shell 命令（仿真工具、构建脚本、测试等）：

```python
# Agent ReAct 中自动调用：
run_command("python simulate.py --config cfg.json", timeout=60)
run_command("make build", cwd="./project")

# 通过 FileTools 注册：
from core.file_tools import FileTools
ft = FileTools("./project")
for tool in ft.get_tools():  # 包含 run_command
    agent.register_tool(tool)
```

### WorkflowEngine — 工作流编排

```python
from orchestration.workflow import WorkflowEngine, Node, Task

# DAG 模式
wf = WorkflowEngine("pipeline")
wf.add_task("research", Node(Task("research", "Research topic"), "agent_a"))
wf.add_task("write", Node(Task("write", "Write report"), "agent_b"))
wf.add_edge("research", "write")  # research → write

# 固定链模式（推荐）
wf = WorkflowEngine.chain("game", [
    ("design", Task("design", "Design game"), "architect"),
    [("track", Task("track", "Develop track"), "coder"),   # 并行组
     ("car", Task("car", "Develop car"), "coder")],
    ("integrate", Task("integrate", "Merge"), "coder"),
])

# 执行
result = wf.run(agents={"architect": a1, "coder": a2})
```

### Review Gate — 自动返工

```python
# 实现任务关联评审门，最多返工 2 次
wf.add_task("implement", Node(
    Task("implement", "Build the game"),
    "coder",
    review_gate="review",      # 关联评审任务
    max_passes=2,              # 最多 2 轮（原始 + 1 次返工）
))
wf.add_task("review", Node(
    Task("review", "Review code quality"),
    "reviewer",
))

# 执行流程：
# implement → review → approved? → 下一任务
#                    → rejected? → feedback → implement（返工）→ review
```

评审 Agent 使用 `review_decision(approved=True/False, feedback=...)` 工具提交 verdict。

### Loop Condition — 条件循环

DAG 节点支持 **循环执行直到条件满足**，用于需要迭代的场景（仿真 → 分析 → 调整，直到指标通过）：

```python
wf.add_task("simulate", Node(
    Task("simulate", "Run simulation with positive/negative cases"),
    "executor",
    loop_condition=lambda outputs: outputs.get("pass_rate", 0) >= 0.8,
    loop_max_iterations=5,
))
```

执行流程：
- DAG 全部完成后，检查 `loop_condition(outputs)`
- 返回 `True` → 继续下一任务
- 返回 `False` → 注入反馈 → 重新执行该 task → 再检查
- 耗尽 `loop_max_iterations` 仍未满足 → workflow FAILED

支持 Register-Memory 压缩，多轮迭代不膨胀上下文。

### Register-Memory 对话压缩

解决多轮返工后的上下文膨胀问题：

```
┌─────────────────────────────────────────────────┐
│  Layer        │ Analogy      │ Content           │
├───────────────┼──────────────┼───────────────────┤
│ Conversation  │ CPU Register │ System + 最近10条 │
│ IMPLEMENTATION│ L1 Cache     │ 文件清单/检查清单 │
│ _SUMMARY.md   │              │                   │
│ logs/round_N  │ RAM          │ 完整对话归档      │
│ _conversation │              │                   │
│ .json         │              │                   │
│ design.md     │ 持久存储     │ 架构设计文档      │
└─────────────────────────────────────────────────┘
```

每轮返工后自动执行：
1. `archive_round(pass_num=N, out_dir="logs")` — 保存完整对话到 JSON
2. `compact(keep_recent=10)` — 压缩为 system + 最近10条 + `[History Archive]` 引用

关键修复：`compact()` 截断点避开 `tool` 消息，防止 API 400 错误。

### 文件版本化

每次 `write_file()` 自动备份旧版本：

```
outputs/my_game/
  ├── index.html                    ← 当前版本
  ├── versions/
  │     └── 20250603_142011/
  │           └── index.html        ← 上一版本备份
  └── logs/
        ├── round_0_conversation.json
        └── round_1_conversation.json
```

### 断点续跑

```python
# 失败后自动保存 checkpoint
# 从断点恢复
result = wf.resume(agents={"agent": agent})
# 自动跳过已完成的 Task，从失败处继续
```

### Human-in-the-Loop 审批

```python
wf = WorkflowEngine.chain("pipeline", [
    ("deploy", Node(Task("deploy", "..."), "ops", requires_approval=True)),
])
# 运行到 deploy 时暂停，等待人工审批
# 前端面板会显示 "Needs Approval" 按钮
```

### FileContextManager — 超大文件

```python
from core.file_context import FileContextManager

ctx = FileContextManager(root="./project")

# 搜索（grep，零索引开销）
results = ctx.search_code("def foo", path="src", file_type=".py")

# 分段读取（避免全量加载）
slice = ctx.read_file_range("large.py", offset=200, limit=50)

# 写入文件（自动版本化备份）
ctx.write_file("src/new.py", content="...")

# 注册为 Agent 工具
from core.file_tools import FileTools
ft = FileTools("./project")
for tool in ft.get_tools():
    agent.register_tool(tool)
# Agent 获得 search_code / read_file_range / list_files / file_summary /
#       search_with_context / write_file / make_dir / run_command 能力
```

---

## 前端监控面板

### 功能

| 面板 | 功能 |
| ---- | ---- |
| **StatusBar** | Token 使用、系统健康、连接状态 |
| **AgentSidebar** | 所有 Agent 列表，点击查看详情 |
| **AgentDetail** | 消息流、ReAct 步骤、快照管理 |
| **MessageFlow** | 消息流可视化，支持 **Round 分组**（Original / Rework #1 / ...），可折叠展开 |
| **WorkflowDAG** | DAG 可视化，含 Review Gate 边、执行状态、审批/拒绝标记 |
| **WorkflowBuilder** | 工作流定义构建器 |
| **WorkflowLauncher** | 工作流启动面板 |
| **WorkflowControl** | 暂停/恢复/终止、审批/拒绝、进度条 |
| **DemoTemplates** | 一键启动预配置多 Agent Demo（3D 赛车 / 创新 Snake） |
| **ArtifactsPanel** | 产物文件预览、复制、下载 |
| **EventLog** | SSE 实时事件流（所有上下文变更） |
| **InterventionPanel** | 插入消息、暂停/恢复/终止 Agent |
| **HelpPanel** | 帮助文档 |

### Demo 模板

| Demo | Agents | 描述 |
| ---- | ------ | ---- |
| **3D Racing Game** | architect → coder → reviewer | Babylon.js 单文件赛车游戏，含物理/相机/HUD/圈速系统 |
| **Innovative Snake** | architect → coder → reviewer | HTML5 Canvas 创新贪吃蛇，含传送/冲刺/道具/连击 |

### 开发模式热修改

```bash
# 前端代码修改 → Vite HMR 自动刷新
# 后端 Python 修改 → 保存即生效（threaded 模式）
# .env 修改 → 需重启 launch.py
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `DEEPSEEK_API_KEY` | — | DeepSeek API Key |
| `API_HOST` | `0.0.0.0` | API 监听地址 |
| `API_PORT` | `5000` | API 端口 |
| `FRONTEND_PORT` | `5173` | 前端 Dev Server 端口 |
| `AGENT_OUTPUTS_DIR` | `./outputs` | Agent 产物输出目录 |
| `DB_PATH` | `/tmp/agent_workflow/context_hub.db` | SQLite 路径 |
| `CHECKPOINT_DIR` | `/tmp/agent_workflow/checkpoints` | Checkpoint 目录 |
| `DEMO_MODE` | `false` | 演示模式 |

---

## API 端点

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/api/agents` | 所有 Agent 摘要 |
| GET | `/api/agents/<id>` | Agent 详情（消息/步骤） |
| GET | `/api/status` | 系统状态 |
| GET | `/api/stats` | 运行统计（token、事件数等） |
| GET | `/api/config` | 当前配置 |
| GET | `/api/events` | **SSE** 实时事件流 |
| POST | `/api/intervene` | 提交干预操作 |
| GET | `/api/snapshots` | 快照列表 |
| POST | `/api/snapshot` | 创建全局快照 |
| POST | `/api/rollback` | 回滚到快照 |
| GET | `/api/workflow/tasks` | Workflow 任务列表 |
| GET | `/api/workflow/progress` | Workflow 执行进度 |
| POST | `/api/workflow/pause` | 暂停 Workflow |
| POST | `/api/workflow/resume` | 恢复 Workflow |
| POST | `/api/workflow/abort` | 终止 Workflow |
| POST | `/api/workflow/approve` | 审批通过 Task |
| POST | `/api/workflow/reject` | 拒绝 Task |
| GET | `/api/rule_engine` | 规则引擎状态 |
| POST | `/api/rule_engine/start` | 启动规则引擎 |
| POST | `/api/rule_engine/stop` | 停止规则引擎 |

---

## 测试

```bash
# 全部测试（pytest）
pytest tests/ -v --tb=short

# 单独模块测试
pytest tests/test_workflow_engine.py -v
pytest tests/test_agent.py -v
pytest tests/test_file_context.py -v
pytest tests/test_state.py -v
pytest tests/test_checkpoint.py -v
pytest tests/test_tool.py -v
pytest tests/test_validation.py -v
pytest tests/test_report.py -v

# 示例脚本测试
python examples/test_workflow_merged.py
python examples/test_file_context.py
python examples/test_deepseek.py
```

测试模块（9个）：
- `test_workflow_engine.py` — WorkflowEngine、ArtifactCollector、Review Gate
- `test_agent.py` — ReAct 循环、AgentConfig
- `test_file_context.py` — FileContextManager、搜索/读取/写入
- `test_state.py` — WorkflowState、TaskState
- `test_checkpoint.py` — Checkpoint 序列化/恢复
- `test_tool.py` — @tool 装饰器、JSON Schema 推断
- `test_validation.py` — 验证器
- `test_report.py` — 报告生成
- `conftest.py` — MockLLM 等测试 fixture

---

## 设计原则

1. **奥卡姆剃刀** — 不引入不必要的复杂度（无向量数据库、无 LangChain 依赖）
2. **纯 Python 标准库** — 核心层零外部依赖
3. **装饰器推断** — `@tool` 自动从 type hints + docstring 生成 JSON Schema
4. **上下文隔离** — 每个 Task 独立 Conversation，避免历史累积
5. **ContextHub 纯监控** — 不控制执行流程，仅事件收集与审计
6. **三层递进文件管理** — grep 检索 → offset/limit 分段 → LRU 缓存
7. **Register-Memory 模型** — 对话是寄存器（小），文件是内存（大），永不重复存储
8. **Review Gate 闭环** — 评审→反馈→返工→再评审，直到通过或耗尽次数
9. **Skill 扩展** — Prompt + Tools 打包为可复用能力包，Agent 按需加载
10. **本地工具执行** — Agent 可直接调用 shell 命令，打通仿真/构建/测试等本地环境

---

## 版本历史

### v3.1.0 (2026-06-04)

- **Skill 系统** — 恢复 `core/skill.py`，支持 Skill/SkillRegistry：注册、组合、参数化渲染、应用到 Agent
- **本地工具执行** — `run_command` 工具（`FileTools`），Agent 可直接调用 shell 命令运行仿真/构建/测试
- **条件循环工作流** — `Node(loop_condition=..., loop_max_iterations=...)`，DAG 完成后循环执行直到条件满足
- **代码瘦身** — 删除 9,500+ 行未使用代码（persistence、skill stub、report、logging_config、presets 等）

### v3.0.0 (2026-06-03)

- **Register-Memory 对话压缩** — `archive_round()` + `compact()` 解决多轮返工上下文膨胀
- **Review Gate 自动返工** — 结构化 `review_decision()` + feedback 注入 + `max_passes` 限制
- **文件版本化** — `write_file()` 自动备份旧版本到 `versions/{timestamp}/`
- **Round 消息分组** — 前端 MessageFlow 按返工轮次分组显示，带颜色编码
- **Demo 模板面板** — 一键启动 Babylon.js 赛车 / 创新 Snake 多 Agent 工作流
- **API 扩展** — 新增 workflow 控制端点（pause/resume/abort/approve/reject）
- **测试套件** — 9 个 pytest 模块，覆盖引擎、Agent、文件上下文、状态机
- **Bug 修复** — `compact()` 截断保护（避开 `tool` 消息），coder 失败时正确终止 workflow
