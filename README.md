# Agent Workflow Framework

> DAG-based multi-agent orchestration framework with real-time monitoring, review gates, and register-memory conversation compression.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![React 19](https://img.shields.io/badge/react-19-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/typescript-5.9+-3178C6.svg)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## What Is This?

A **multi-agent workflow orchestration framework** that coordinates LLM-powered agents through DAG-defined tasks. It supports review gates with automatic rework, real-time monitoring via a React dashboard, and a novel register-memory architecture for long-running conversations.

**Typical use case:** Generate complete game demos (design → code → review → iterate) with multiple specialized agents working together.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ Monitor  │ │ Builder  │ │  Config  │ │ Demo Launch  │   │
│  │ (Message │ │ (DAG     │ │ (Agent   │ │ (Racing/     │   │
│  │  Flow)   │ │  Editor) │ │  Params) │ │  Snake)      │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘   │
│       └─────────────┴─────────────┴──────────────┘          │
│                         │ SSE / REST                         │
└─────────────────────────┼───────────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────────┐
│                    Backend (Flask + asyncio)                 │
│  ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐   │
│  │ API Server   │  │  Workflow   │  │   Context Hub    │   │
│  │ (REST/SSE)   │◄─┤   Engine    │◄─┤  (Monitoring)    │   │
│  └──────────────┘  └──────┬──────┘  └──────────────────┘   │
│                           │                                  │
│              ┌────────────┼────────────┐                    │
│              ▼            ▼            ▼                    │
│         ┌────────┐  ┌────────┐  ┌──────────┐              │
│         │ Agent  │  │ Agent  │  │  Review  │              │
│         │(Design)│  │(Code)  │  │  (Gate)  │              │
│         └───┬────┘  └───┬────┘  └────┬─────┘              │
│             │           │            │                     │
│             └───────────┴────────────┘                     │
│                         │                                   │
│              ┌──────────┴──────────┐                       │
│              ▼                     ▼                       │
│      ┌──────────────┐   ┌──────────────────┐              │
│      │ DeepSeek API │   │ File System      │              │
│      │ (or OpenAI)  │   │ (Artifacts/Logs) │              │
│      └──────────────┘   └──────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 20+
- DeepSeek API key (or OpenAI-compatible API)

### 1. Install Backend Dependencies

```bash
pip install -r requirements.txt
# Or with dev dependencies:
pip install -r requirements-dev.txt
```

### 2. Configure Environment

Create `.env` in the project root:

```bash
DEEPSEEK_API_KEY=sk-your-api-key-here
API_PORT=5000
FRONTEND_PORT=5173
API_HOST=0.0.0.0
AGENT_OUTPUTS_DIR=/tmp/agent_workflow/outputs
```

### 3. Start Everything

```bash
# Backend + frontend in one command
python agent_workflow/launch.py

# Or backend only
python agent_workflow/launch.py --api-only

# With demo mode (simulated agents)
python agent_workflow/launch.py --demo
```

The dashboard opens at `http://localhost:5173`.

---

## Core Features

### 1. DAG Workflow Orchestration

Define workflows as directed acyclic graphs. The engine uses Kahn's topological sorting with **layered parallel execution** — independent tasks run concurrently via `asyncio.gather`.

```python
from orchestration.workflow.engine import WorkflowEngine, Node

engine = WorkflowEngine(name="my_game")
engine.add_node(Node("design", agent=designer))
engine.add_node(Node("implement", agent=coder))
engine.add_node(Node("review", agent=reviewer))
engine.add_edge("design", "implement")
engine.add_edge("implement", "review")

result = await engine.execute()
```

### 2. Review Gate with Automatic Rework

Any task can declare a `review_gate` — another task that must approve before proceeding. If rejected, the implement task automatically retries with reviewer feedback.

- **max_passes**: Limit rework iterations (default: 2)
- **Structured review**: `review_decision(approved=True/False, feedback=...)` tool
- **Conversation compression**: After each rework pass, full history is archived and the working context is compacted (see §4)

```python
Node("implement", agent=coder, review_gate="review", max_passes=2)
Node("review", agent=reviewer)
```

### 3. ReAct Agent Loop

Each agent runs a **Thought → Action → Observation** loop:

- **Thought**: LLM reasons about the task
- **Action**: Calls registered tools (`write_file`, `read_file_range`, `done`, etc.)
- **Observation**: Tool results fed back into conversation

Configurable limits: `max_iterations`, `budget_tokens`, `temperature`, `checkpoint_enabled`.

### 4. Register-Memory Conversation Model

Solves the long-context problem for multi-pass workflows:

| Layer                                    | Analogy            | Content                                              |
| ---------------------------------------- | ------------------ | ---------------------------------------------------- |
| **Conversation**                   | CPU Register       | System prompt + last 10 messages + archive reference |
| **IMPLEMENTATION_SUMMARY.md**      | L1 Cache           | Structured checklist, file list, known issues        |
| **logs/round_N_conversation.json** | RAM                | Full conversation archive per round                  |
| **design.md**                      | Persistent Storage | Architecture specification                           |

After each rework pass:

1. `archive_round()` — save full conversation to `logs/round_{N}_conversation.json`
2. `compact()` — keep system prompt + last 10 messages, replace middle with `[History Archive]` reference

Key fix: truncation point guards against landing on `tool` messages (which would violate API message sequence contracts).

### 5. File Versioning

Every `write_file()` call automatically backs up the old version:

```
outputs/my_game/
  ├── index.html          ← current version
  ├── versions/
  │     └── 20250603_142011/
  │           └── index.html   ← previous version
  └── logs/
        ├── round_0_conversation.json
        └── round_1_conversation.json
```

### 6. File Context Manager

Lightweight file operations for agents — no vector DB, no embeddings:

- `search_code(pattern)` — grep-based code search
- `read_file_range(path, offset, limit)` — partial reads (avoid loading entire files)
- `list_files(path)` — directory tree with metadata
- `file_summary(path)` — imports, class/function signatures
- `search_with_context(pattern)` — search + auto-read matching context
- `write_file(path, content)` — write with automatic version backup
- `make_dir(path)` — create directories

### 7. Real-Time Monitoring Dashboard

React-based frontend with:

- **Agent Message Flow** — Live conversation stream with round grouping (Original / Rework #1 / Rework #2...), syntax-highlighted code blocks, foldable long messages
- **Workflow DAG** — Visual task graph with execution state (pending → running → completed/failed), review gate edges, approval/rejection badges
- **Event Log** — Real-time SSE event stream (system, agent, task, workflow events)
- **Artifacts Panel** — Generated files with preview, copy, download
- **Intervention Panel** — Pause, resume, abort, approve, reject workflow execution
- **Demo Templates** — One-click launch pre-configured multi-agent demos
- **Status Bar** — Token usage, system health, connection status

### 8. Demo Templates

Pre-built multi-agent workflows:

| Demo                       | Agents                         | Description                                                             |
| -------------------------- | ------------------------------ | ----------------------------------------------------------------------- |
| **3D Racing Game**   | architect → coder → reviewer | Babylon.js single-file arcade racing game with physics, HUD, lap system |
| **Innovative Snake** | architect → coder → reviewer | HTML5 Canvas snake with warp mode, dash boost, power-ups, combo chains  |

### 9. Human-in-the-Loop

Tasks can require manual approval:

- `requires_approval=True` — workflow pauses, waits for human via dashboard
- Pause / Resume / Abort — runtime control via API or dashboard
- Review gate decisions can be overridden manually

### 10. Checkpoint & Resume

Workflow state is serialized to JSON (`WorkflowCheckpoint`). Supports:

- **Crash recovery** — resume from last completed task
- **Manual rollback** — restore to any snapshot
- **Step-level checkpoints** — per-agent iteration checkpoints (optional)

---

## Project Structure

```
agent-workflow/
├── agent_workflow/              # Backend (Python)
│   ├── api_server.py            # Flask REST API + SSE endpoint
│   ├── launch.py                # Unified launcher (backend + frontend)
│   ├── core/                    # Core framework
│   │   ├── agent.py             # ReAct Agent loop
│   │   ├── llm.py               # LLM abstraction (DeepSeek/OpenAI)
│   │   ├── memory.py            # Conversation + Snapshot + compact()
│   │   ├── tool.py              # Tool registry + @tool decorator
│   │   ├── file_tools.py        # Agent file operations (write/read/search)
│   │   ├── file_context.py      # FileContextManager (search, read, summary)
│   │   ├── review_tools.py      # Structured review decision tool
│   │   └── skill.py             # Agent skill system
│   ├── orchestration/           # Workflow orchestration
│   │   ├── workflow.py          # Public API (WorkflowEngine facade)
│   │   ├── task.py              # Task definition
│   │   ├── context_hub.py       # Event bus + monitoring
│   │   ├── rules.py             # SimpleRuleEngine
│   │   └── workflow/            # Execution engine
│   │       ├── engine.py        # DAG executor (Kahn + asyncio)
│   │       ├── state.py         # Execution state machines
│   │       └── checkpoint.py    # Checkpoint serialization
│   ├── examples/                # Standalone example scripts
│   └── utils/                   # Utilities (logging, reports)
├── app/                         # Frontend (React + TypeScript)
│   ├── src/
│   │   ├── App.tsx              # Root component
│   │   ├── main.tsx             # Entry point
│   │   ├── hooks/useApi.ts      # API client hooks
│   │   ├── types/index.ts       # TypeScript types
│   │   └── components/
│   │       ├── MessageFlow.tsx      # Agent message stream
│   │       ├── WorkflowDAG.tsx      # DAG visualization
│   │       ├── WorkflowControl.tsx  # Pause/resume/abort
│   │       ├── WorkflowBuilder.tsx  # Workflow definition UI
│   │       ├── WorkflowLauncher.tsx # Launch panel
│   │       ├── DemoTemplates.tsx    # Pre-built demos
│   │       ├── AgentDetail.tsx      # Agent inspector
│   │       ├── AgentSidebar.tsx     # Agent list
│   │       ├── ArtifactsPanel.tsx   # Generated files
│   │       ├── InterventionPanel.tsx# Manual controls
│   │       ├── EventLog.tsx         # Real-time events
│   │       ├── StatusBar.tsx        # System status bar
│   │       ├── HelpPanel.tsx        # Help documentation
│   │       └── ui/                  # shadcn/ui components (40+)
│   ├── package.json
│   └── vite.config.ts
├── tests/                       # Test suite (pytest)
│   ├── test_workflow_engine.py
│   ├── test_agent.py
│   ├── test_file_context.py
│   └── ...
├── pyproject.toml               # Python package config
├── requirements.txt             # Production deps
├── requirements-dev.txt         # Dev + test deps
└── README.md                    # This file
```

---

## API Endpoints

| Method | Path                       | Description                                             |
| ------ | -------------------------- | ------------------------------------------------------- |
| GET    | `/api/agents`            | List all agents                                         |
| GET    | `/api/agents/<id>`       | Agent detail (messages, steps)                          |
| GET    | `/api/status`            | System status                                           |
| GET    | `/api/events`            | **SSE** real-time event stream                    |
| POST   | `/api/intervene`         | Submit intervention (pause/resume/abort/approve/reject) |
| GET    | `/api/workflow/tasks`    | Workflow task list                                      |
| GET    | `/api/workflow/progress` | Execution progress                                      |
| POST   | `/api/workflow/pause`    | Pause workflow                                          |
| POST   | `/api/workflow/resume`   | Resume workflow                                         |
| POST   | `/api/workflow/abort`    | Abort workflow                                          |
| POST   | `/api/workflow/approve`  | Approve pending task                                    |
| POST   | `/api/workflow/reject`   | Reject pending task                                     |
| GET    | `/api/stats`             | Token usage & event statistics                          |
| GET    | `/api/config`            | Current configuration                                   |

---

## Development

### Run Tests

```bash
pytest tests/ -v --tb=short
```

### Type Check Frontend

```bash
cd app
npx tsc --noEmit
```

### Lint Frontend

```bash
cd app
npm run lint
```

---

## Changelog

### v3.0.0 (2026-06-03)

- **Register-Memory Model** — Conversation compression with `archive_round()` + `compact()` to handle multi-pass rework without exceeding LLM context windows
- **Review Gate Rework** — Structured `review_decision()` tool with automatic retry loop, max_passes limit, and feedback injection
- **File Versioning** — `write_file()` automatically backs up old versions to `versions/{timestamp}/`
- **Round Visualization** — Frontend message flow groups messages by rework round (Original / Rework #1 / ...) with color-coded borders
- **Babylon.js Racing Demo** — Redesigned 3D racing game demo using Babylon.js (single-file `index.html`) with 11-section checklist-based implement/review prompts
- **Bug Fixes** — Compact truncation guard (avoids cutting on `tool` messages), coder failure handling during rework (no longer re-executes reviewer on stale code)
- **9 test modules** covering engine, agent, file context, state, checkpoint, tool, validation, report

---

## License

MIT License — see [pyproject.toml](pyproject.toml) for details.
