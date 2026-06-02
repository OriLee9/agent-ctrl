"""
Agent Workflow API Server — 前端监控面板的数据后端。

启动方式:
    独立启动:    python api_server.py
    集成启动:    python launch.py (同时启动前端 dev server)

接口:
- GET  /api/agents              所有 Agent 摘要
- GET  /api/agents/<id>         Agent 详情（消息、步骤）
- GET  /api/status              系统整体状态
- GET  /api/events              SSE 实时事件流
- POST /api/intervene           提交干预操作
- GET  /api/snapshots           快照列表
- POST /api/snapshot            创建全局快照
- POST /api/rollback            回滚到快照
- GET  /api/rule_engine         规则引擎状态
- POST /api/rule_engine/start   启动规则引擎
- POST /api/rule_engine/stop    停止规则引擎
- GET  /api/workflow/tasks      Workflow 任务列表
- GET  /api/workflow/progress   Workflow 执行进度
- POST /api/workflow/pause      暂停 Workflow
- POST /api/workflow/resume     恢复 Workflow
- POST /api/workflow/abort      终止 Workflow
- POST /api/workflow/approve    审批通过 Task
- POST /api/workflow/reject     拒绝 Task
- GET  /api/stats               运行统计（token、事件数等）
- GET  /api/config              当前配置
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from core.agent import Agent, AgentConfig
from core.file_tools import FileTools
from core.llm import DeepSeekLLM, llm_from_env, resolve_deepseek_model
from core.tool import tool
from orchestration.context_hub import ContextEvent, ContextHub, Intervention
from orchestration.rules import RuleConfig, SimpleRuleEngine
from orchestration.task import Task
from orchestration.workflow import WorkflowEngine, WorkflowState
from orchestration.workflow.engine import Node

# ── 产物目录 ──────────────────────────────────────────────
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "/tmp/agent_workflow/artifacts"))
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


@tool
def save_file(filepath: str, content: str) -> dict:
    """Save content to a file. The file will be tracked as an artifact."""
    # 安全处理：防止目录遍历（支持 Windows / Unix）
    p = Path(filepath)
    # 拒绝绝对路径和父目录引用
    if p.is_absolute() or ".." in p.parts:
        return {"result": f"Error: Invalid path '{filepath}'", "_artifacts": []}

    # 构建目标路径并解析（消除符号链接等）
    full_path = (ARTIFACTS_DIR / p).resolve()
    # 二次验证：解析后的路径必须在产物目录内
    if not full_path.is_relative_to(ARTIFACTS_DIR.resolve()):
        return {"result": f"Error: Path '{filepath}' escapes artifacts directory", "_artifacts": []}

    # 安全通过后才写入
    full_path.parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)

    rel_path = str(full_path.relative_to(ARTIFACTS_DIR.resolve()))
    safe_name = p.name
    return {
        "result": f"Saved: {safe_name} ({len(content)} chars)",
        "_artifacts": [rel_path],
    }

app = Flask(__name__)
CORS(app)

# ── 全局状态（可被外部注入）────────────────────────────────

hub = ContextHub()
rule_engine: SimpleRuleEngine | None = None
active_workflow: WorkflowEngine | None = None
# 新增: workflow 定义暂存 + Agent 注册表
_pending_workflow_def: dict[str, Any] | None = None
_registered_agents: dict[str, Agent] = {}
_workflow_thread: threading.Thread | None = None

_event_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=2000)
_event_count = 0

# 输出目录（写入产物）
OUTPUTS_DIR = os.environ.get("AGENT_OUTPUTS_DIR", os.path.join(os.path.dirname(__file__) or ".", "outputs"))


def _create_agent_with_tools(
    agent_id: str, api_key: str, model: str,
    temperature: float | None, max_iterations: int, system_prompt: str,
    workspace: str | None = None,
) -> Agent:
    """创建 Agent 实例，自动挂载文件工具（读写均支持）。

    Args:
        workspace: 工作目录路径。为 None 则自动生成 `outputs/{agent_id}/`。
    """
    if workspace is None:
        workspace = os.path.join(OUTPUTS_DIR, agent_id)
    os.makedirs(workspace, exist_ok=True)

    ft = FileTools(root=workspace)
    file_tools = ft.get_tools()

    llm = DeepSeekLLM(api_key=api_key, model=model)
    agent = Agent(
        llm=llm,
        tools=file_tools,
        config=AgentConfig(
            max_iterations=max_iterations,
            temperature=temperature,
        ),
        name=agent_id,
        system_prompt=system_prompt,
    )
    return agent


def _event_handler(event_type: str, data: dict[str, Any]) -> None:
    """全局事件处理器 — 事件入队列供 SSE 消费。"""
    global _event_count
    try:
        _event_queue.put_nowait({
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        })
        _event_count += 1
    except queue.Full:
        pass


hub.on_all(_event_handler)


# ── API 路由 ──────────────────────────────────────────────

@app.route("/api/agents", methods=["GET"])
def get_agents():
    """所有 Agent 摘要。"""
    agents = []
    for aid in hub.list_sessions():
        summary = hub.session_summary(aid)
        if summary:
            # 统一字段：前端期望 agent_id，后端使用 session_id
            summary["agent_id"] = summary.get("session_id", aid)
            agents.append(summary)
    return jsonify({"agents": agents})


@app.route("/api/agents/<path:agent_id>", methods=["GET"])
def get_agent(agent_id: str):
    """Agent 详情（含消息、步骤、快照）。支持包含 '/' 的 agent_id（如 task conversation）。"""
    conv = hub.get(agent_id)
    if not conv:
        return jsonify({"error": "Agent not found"}), 404

    return jsonify({
        "agent_id": agent_id,
        "summary": conv.summary(),
        "messages": [m.to_dict() for m in conv.get_messages()],
        "steps": [s.to_dict() for s in conv.get_steps()],
        "snapshots": conv.list_snapshots(),
        "transcript": conv.to_transcript(),
    })


@app.route("/api/status", methods=["GET"])
def get_status():
    """系统整体状态。"""
    re_running = rule_engine is not None and getattr(rule_engine, "_running", False)
    wf_state = active_workflow.state.value if active_workflow else "none"
    return jsonify({
        "agent_count": len(hub.list_sessions()),
        "agents": hub.list_sessions(),
        "snapshot_count": 0,
        "rule_engine_running": re_running,
        "workflow_state": wf_state,
        "event_count": _event_count,
    })


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """运行统计。"""
    try:
        event_stats = hub.get_event_stats()
    except Exception:
        event_stats = {"total_events": 0}
    return jsonify({
        **event_stats,
        "event_queue_size": _event_queue.qsize(),
        "sessions": len(hub.list_sessions()),
        "workflow_state": active_workflow.state.value if active_workflow else "none",
    })


@app.route("/api/config", methods=["GET"])
def get_config():
    """当前配置（不含敏感信息）。"""
    return jsonify({
        "framework_version": "3.0",
        "workflow_type": "WorkflowEngine (DAG + V2 merged)",
        "context_hub_db": hub._db_path,
        "api_server": {"cors": True, "event_stream": True},
    })


# ── 干预 ──────────────────────────────────────────────────

@app.route("/api/intervene", methods=["POST"])
def do_intervene():
    """提交干预操作。"""
    data = request.json or {}
    intervention = Intervention(
        type=data.get("type", "insert"),
        target=data.get("target", ""),
        data=data.get("data"),
        reason=data.get("reason"),
    )
    success = hub.intervene(intervention)

    # 对 pause/resume/abort 类型，同时驱动关联的 WorkflowEngine
    if active_workflow and intervention.type in ("pause", "resume", "abort"):
        if intervention.type == "pause":
            active_workflow.pause()
        elif intervention.type == "resume":
            active_workflow.resume_from_pause()
        elif intervention.type == "abort":
            active_workflow.abort()

    return jsonify({"success": success})


# ── 快照 ──────────────────────────────────────────────────

@app.route("/api/snapshots", methods=["GET"])
def get_snapshots():
    """快照列表（v3.0 快照在 Conversation 层面管理）。"""
    return jsonify({"snapshots": []})


@app.route("/api/snapshot", methods=["POST"])
def create_snapshot():
    """创建全局快照。"""
    snap_id = hub.snapshot_all()
    return jsonify({"snapshot_id": snap_id})


@app.route("/api/rollback", methods=["POST"])
def do_rollback():
    """回滚到指定快照（通过干预机制实现）。"""
    data = request.json or {}
    snap_id = data.get("snapshot_id", "")
    return jsonify({"success": False, "message": "Rollback via Conversation-level snapshot in v3.0"})


# ── 规则引擎 ──────────────────────────────────────────────

@app.route("/api/rule_engine", methods=["GET"])
def get_rule_engine():
    """规则引擎状态。"""
    if rule_engine is None:
        return jsonify({"running": False})
    try:
        return jsonify(rule_engine.get_stats())
    except Exception:
        return jsonify({"running": getattr(rule_engine, "_running", False)})


@app.route("/api/rule_engine/start", methods=["POST"])
def start_rule_engine():
    """启动规则引擎。"""
    global rule_engine
    if rule_engine is None:
        config_data = request.get_json(silent=True) or {}
        config = RuleConfig(
            max_repeated_short_thoughts=config_data.get("max_repeated", 3),
            short_thought_threshold=config_data.get("threshold", 20),
        )
        rule_engine = SimpleRuleEngine(hub, config)
    rule_engine.start()
    return jsonify({"running": True})


@app.route("/api/rule_engine/stop", methods=["POST"])
def stop_rule_engine():
    """停止规则引擎。"""
    global rule_engine
    if rule_engine:
        rule_engine.stop()
    return jsonify({"running": False})


# ── Workflow 控制 ─────────────────────────────────────────

@app.route("/api/workflow/tasks", methods=["GET"])
def get_workflow_tasks():
    """Workflow 任务列表。"""
    if active_workflow is None:
        return jsonify({"tasks": []})
    return jsonify({"tasks": active_workflow.list_tasks()})


@app.route("/api/workflow/progress", methods=["GET"])
def get_workflow_progress():
    """Workflow 执行进度。"""
    if active_workflow is None:
        return jsonify({
            "state": "none",
            "progress": 0,
            "current_task": None,
            "completed_tasks": 0,
            "total_tasks": 0,
            "elapsed": 0,
            "task_execution_states": {},
        })
    state = active_workflow.state
    tasks = active_workflow.list_tasks()
    exec_obj = active_workflow._current_execution
    completed = sum(
        1 for t in tasks
        if exec_obj and t["name"] in exec_obj.task_executions
        and exec_obj.task_executions[t["name"]].state.value in ("completed", "recovered")
    ) if exec_obj else 0
    total = len(tasks)
    progress = (completed / total * 100) if total > 0 else 0
    current = exec_obj.current_task if exec_obj else None
    elapsed = exec_obj.total_elapsed if exec_obj else 0
    # 每个 task 的执行状态摘要
    task_states = {}
    if exec_obj:
        for name, te in exec_obj.task_executions.items():
            task_states[name] = {
                "state": te.state.value,
                "agent_id": te.agent_id,
                "elapsed": te.elapsed,
                "error": te.error,
                "retry_count": te.retry_count,
                "artifacts": te.artifacts,
            }
    return jsonify({
        "state": state.value,
        "progress": progress,
        "current_task": current,
        "completed_tasks": completed,
        "total_tasks": total,
        "elapsed": elapsed,
        "checkpoint_exists": active_workflow.has_checkpoint(),
        "task_execution_states": task_states,
    })


@app.route("/api/workflow/execution", methods=["GET"])
def get_workflow_execution():
    """Workflow 完整执行详情（含每个 task 的执行记录、产物、DAG 边）。"""
    if active_workflow is None:
        return jsonify({
            "defined": False,
            "workflow_id": None,
            "name": None,
            "state": "none",
            "tasks": [],
            "edges": [],
            "task_executions": {},
            "execution_order": [],
            "total_elapsed": 0,
            "error": None,
        })
    # DAG 边
    edges = []
    for src, targets in active_workflow._edges.items():
        for tgt in targets:
            edges.append({"from": src, "to": tgt})
    # Task 定义
    tasks = active_workflow.list_tasks()
    # 执行记录
    exec_obj = active_workflow._current_execution
    task_executions = {}
    execution_order = []
    total_elapsed = 0
    error = None
    if exec_obj:
        execution_order = list(exec_obj.task_executions.keys())
        total_elapsed = exec_obj.total_elapsed
        error = exec_obj.error
        for name, te in exec_obj.task_executions.items():
            task_executions[name] = te.to_dict()
    return jsonify({
        "defined": True,
        "workflow_id": active_workflow.workflow_id,
        "name": active_workflow.name,
        "state": active_workflow.state.value,
        "tasks": tasks,
        "edges": edges,
        "task_executions": task_executions,
        "execution_order": execution_order,
        "total_elapsed": total_elapsed,
        "error": error,
    })


@app.route("/api/workflow/pause", methods=["POST"])
def wf_pause():
    """暂停 Workflow。"""
    if active_workflow:
        active_workflow.pause()
    return jsonify({"success": True, "state": "paused"})


@app.route("/api/workflow/resume", methods=["POST"])
def wf_resume():
    """恢复 Workflow。"""
    if active_workflow:
        active_workflow.resume_from_pause()
    return jsonify({"success": True, "state": "running"})


@app.route("/api/workflow/abort", methods=["POST"])
def wf_abort():
    """终止 Workflow。"""
    if active_workflow:
        active_workflow.abort()
    return jsonify({"success": True, "state": "aborted"})


@app.route("/api/workflow/approve", methods=["POST"])
def wf_approve():
    """审批通过 Task。"""
    data = request.json or {}
    task_name = data.get("task_name", "")
    if active_workflow:
        active_workflow.approve_task(task_name)
    return jsonify({"success": True})


@app.route("/api/workflow/reject", methods=["POST"])
def wf_reject():
    """拒绝 Task。"""
    data = request.json or {}
    task_name = data.get("task_name", "")
    if active_workflow:
        active_workflow.reject_task(task_name)
    return jsonify({"success": True})


# ── Workflow 定义与启动（v3.1 新增）───────────────────────


@app.route("/api/workflow/definition", methods=["GET"])
def get_workflow_definition():
    """返回当前 workflow 的结构定义（DAG 节点与边）。"""
    if _pending_workflow_def:
        return jsonify({"defined": True, "workflow": _pending_workflow_def})
    if active_workflow:
        tasks = active_workflow.list_tasks()
        edges = []
        for src, targets in active_workflow._edges.items():
            for tgt in targets:
                edges.append({"from": src, "to": tgt})
        return jsonify({
            "defined": True,
            "workflow": {
                "name": active_workflow.name,
                "workflow_id": active_workflow.workflow_id,
                "tasks": tasks,
                "edges": edges,
            },
        })
    return jsonify({"defined": False, "workflow": None})


@app.route("/api/workflow/define", methods=["POST"])
def define_workflow():
    """接受前端传来的 task/edge 定义，构建 WorkflowEngine 暂存。

    请求体:
        {
            "name": "my_workflow",
            "tasks": [
                {"name": "research", "description": "Research...", "agent_id": "researcher",
                 "requires_approval": false, "max_retries": 2, "temperature": 0.7},
                ...
            ],
            "edges": [
                {"from": "research", "to": "write"},
                ...
            ]
        }
    """
    global _pending_workflow_def
    data = request.json or {}

    name = data.get("name", "workflow")
    mode = data.get("mode", "free")
    tasks = data.get("tasks", [])
    edges = data.get("edges", [])

    if not tasks:
        return jsonify({"error": "At least one task required"}), 400

    _pending_workflow_def = {
        "name": name,
        "mode": mode,
        "tasks": tasks,
        "edges": edges,
    }

    # 构建 WorkflowEngine
    wf = WorkflowEngine(name=name, mode=mode)
    for t in tasks:
        node = Node(
            task=Task(
                name=t["name"],
                description=t.get("description", ""),
                expected_output=t.get("expected_output"),
            ),
            agent_id=t.get("agent_id", ""),
            requires_approval=t.get("requires_approval", False),
            max_retries=t.get("max_retries", 2),
            temperature=t.get("temperature"),
            review_gate=t.get("review_gate"),
            max_passes=t.get("max_passes", 1),
        )
        wf.add_task(t["name"], node)

    for e in edges:
        try:
            wf.add_edge(e["from"], e["to"])
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400

    # 注入为 active_workflow
    global active_workflow
    active_workflow = wf
    inject_workflow(wf)

    return jsonify({
        "success": True,
        "workflow_id": wf.workflow_id,
        "task_count": len(tasks),
        "edge_count": len(edges),
    })


@app.route("/api/workflow/start", methods=["POST"])
def start_workflow():
    """启动暂存的 workflow（后台线程执行）。

    请求体（可选）:
        {"api_key": "sk-xxx"}  # 如不传则使用 .env 中的 DEEPSEEK_API_KEY
    """
    global active_workflow, _workflow_thread

    if active_workflow is None:
        return jsonify({"error": "No workflow defined. POST /api/workflow/define first."}), 400

    if active_workflow.state in (WorkflowState.RUNNING, WorkflowState.WAITING_APPROVAL):
        return jsonify({"error": f"Workflow already in state: {active_workflow.state.value}"}), 409

    data = request.json or {}
    api_key = data.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")

    if not api_key:
        return jsonify({"error": "No API key provided. Pass api_key or set DEEPSEEK_API_KEY in .env"}), 400

    # 确保所有引用的 agent 已注册
    needed_agents: set[str] = set()
    for node in active_workflow._nodes.values():
        if node.agent_id:
            needed_agents.add(node.agent_id)

    # 计算共享 workspace（按 workflow name 分组，同 workflow 的 agent 共用）
    shared_workspace = os.path.join(OUTPUTS_DIR, active_workflow.name)

    for agent_id in needed_agents:
        if agent_id not in _registered_agents:
            # 自动创建 Agent（挂载文件读写工具 + 共享输出目录）
            try:
                agent = _create_agent_with_tools(
                    agent_id=agent_id, api_key=api_key, model=resolve_deepseek_model(),
                    temperature=float(os.environ.get("DEFAULT_TEMPERATURE", "0.7")),
                    max_iterations=int(os.environ.get("DEFAULT_MAX_ITERATIONS", "15")),
                    system_prompt=f"You are the {agent_id} agent. Complete your assigned task thoroughly.",
                    workspace=shared_workspace,
                )
            except Exception:
                agent = _create_agent_with_tools(
                    agent_id=agent_id, api_key=os.environ.get("DEEPSEEK_API_KEY", ""), model=resolve_deepseek_model(),
                    temperature=float(os.environ.get("DEFAULT_TEMPERATURE", "0.7")),
                    max_iterations=int(os.environ.get("DEFAULT_MAX_ITERATIONS", "15")),
                    system_prompt=f"You are the {agent_id} agent. Complete your assigned task thoroughly.",
                    workspace=shared_workspace,
                )
            _registered_agents[agent_id] = agent
            hub.register(agent_id, f"You are the {agent_id} agent.")

    # 设置状态并立即触发 hook，让前端收到 workflow_state_change 事件
    # _run_async 中的 _transition_state 会因状态相同而直接返回，不会重复触发
    with active_workflow._lock:
        active_workflow._state = WorkflowState.RUNNING
    if active_workflow.on_state_change:
        active_workflow.on_state_change(WorkflowState.RUNNING)

    # 后台线程启动
    def _run_workflow():
        try:
            result = active_workflow.run(agents=_registered_agents, hub=hub)
            _event_queue.put_nowait({
                "type": "workflow_complete",
                "data": {
                    "success": result.success,
                    "total_elapsed": result.total_elapsed,
                    "task_count": len(result.task_results),
                },
                "timestamp": time.time(),
            })
        except Exception as exc:
            _event_queue.put_nowait({
                "type": "workflow_error",
                "data": {"error": str(exc)},
                "timestamp": time.time(),
            })

    _workflow_thread = threading.Thread(target=_run_workflow, daemon=True)
    _workflow_thread.start()

    return jsonify({
        "success": True,
        "state": active_workflow.state.value,
        "message": f"Workflow started with {len(needed_agents)} agents",
    })


@app.route("/api/agent/register", methods=["POST"])
def register_agent():
    """注册 Agent（创建 LLM + Agent 并注入 ContextHub）。

    请求体:
        {
            "agent_id": "researcher",
            "api_key": "sk-xxx",            // 可选，不传则用 .env
            "model": "deepseek-v4-pro",    // 可选，默认读取 DEEPSEEK_API_TYPE 配置
            "temperature": 0.7,             // 可选
            "max_iterations": 15,           // 可选
            "system_prompt": "You are...",  // 可选
            "workflow_name": "my_project"   // 可选，指定后所有产物写入 outputs/{workflow_name}/
        }
    """
    try:
        data = request.json or {}
    except Exception:
        data = {}
    agent_id = data.get("agent_id", "")
    if not agent_id:
        return jsonify({"error": "agent_id required"}), 400

    api_key = data.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return jsonify({"error": "No API key. Pass api_key or set DEEPSEEK_API_KEY"}), 400

    model = data.get("model", resolve_deepseek_model())
    temperature = data.get("temperature")
    max_iterations = data.get("max_iterations", 15)
    system_prompt = data.get("system_prompt", f"You are the {agent_id} agent.")

    # 检测 workspace：优先使用传入的 workflow_name，其次检测活跃/待定义的 workflow
    wf_name = data.get("workflow_name")
    if not wf_name:
        if active_workflow:
            wf_name = active_workflow.name
        elif _pending_workflow_def:
            wf_name = _pending_workflow_def.get("name")

    try:
        agent = _create_agent_with_tools(
            agent_id=agent_id, api_key=api_key, model=model,
            temperature=temperature, max_iterations=max_iterations,
            system_prompt=system_prompt,
            workspace=os.path.join(OUTPUTS_DIR, wf_name) if wf_name else None,
        )
    except Exception as e:
        return jsonify({"error": f"Failed to create agent: {e}"}), 400

    try:
        _registered_agents[agent_id] = agent
        hub.register(agent_id, system_prompt)
    except Exception as e:
        return jsonify({"error": f"Registration failed: {e}"}), 500

    return jsonify({
        "success": True,
        "agent_id": agent_id,
        "model": model,
        "max_iterations": max_iterations,
    })


@app.route("/api/agent/templates", methods=["GET"])
def get_agent_templates():
    """返回可用的配置模板（LLM 模型列表、预设工具、默认参数）。"""
    return jsonify({
        "llm_providers": [
            {"id": "deepseek", "name": "DeepSeek", "default_model": "deepseek-chat",
             "models": ["deepseek-chat", "deepseek-reasoner"]},
            {"id": "openai", "name": "OpenAI", "default_model": "gpt-4o-mini",
             "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]},
        ],
        "defaults": {
            "max_iterations": 15,
            "temperature": 0.7,
            "max_retries": 2,
            "retry_delay": 3,
        },
        "task_presets": [
            {"id": "sequential", "name": "Sequential Chain", "description": "Tasks execute one after another"},
            {"id": "parallel", "name": "Parallel Group", "description": "Multiple tasks run simultaneously"},
            {"id": "mapreduce", "name": "Map-Reduce", "description": "Map tasks in parallel, then reduce"},
            {"id": "conditional", "name": "Conditional Branch", "description": "Branch based on previous output"},
        ],
    })


# ── SSE 事件流 ────────────────────────────────────────────

@app.route("/api/events")
def events_stream():
    """SSE 实时事件流。"""
    def generate():
        yield f"data: {json.dumps({'type': 'connected', 'timestamp': time.time()})}\n\n"
        while True:
            try:
                event = _event_queue.get(timeout=15)
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return app.response_class(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── 产物文件服务 ──────────────────────────────────────────

@app.route("/api/artifact")
def get_artifact():
    """读取产物文件内容（支持 ARTIFACTS_DIR 和 OUTPUTS_DIR）。"""
    path = request.args.get("path", "")
    if not path:
        return jsonify({"error": "path parameter required"}), 400

    # 依次尝试: ARTIFACTS_DIR → OUTPUTS_DIR
    bases: list[Path] = [ARTIFACTS_DIR]
    outputs = Path(OUTPUTS_DIR)
    if outputs.exists():
        bases.append(outputs)

    for base in bases:
        try:
            target = (base / path).resolve()
            base_resolved = base.resolve()
            if not str(target).startswith(str(base_resolved)):
                continue
            if target.exists() and not target.is_dir():
                return send_from_directory(str(base), path)
        except Exception:
            continue

    return jsonify({"error": "File not found"}), 404


# ── 前端静态文件（生产模式）─────────────────────────────────

FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "app", "dist"
)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path: str):
    """服务前端静态文件。API 路由优先，其余 fallback 到 index.html。"""
    # API 请求不处理
    if path.startswith("api/"):
        return jsonify({"error": "Not found"}), 404

    # 检查静态文件
    static_file = os.path.join(FRONTEND_DIST, path)
    if path and os.path.exists(static_file) and os.path.isfile(static_file):
        return send_from_directory(FRONTEND_DIST, path)

    # Fallback 到 index.html
    index_html = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_html):
        return send_from_directory(FRONTEND_DIST, "index.html")

    return "Frontend not built. Run 'npm run build' in the app/ directory.", 404


# ── 外部注入接口 ──────────────────────────────────────────

def inject_workflow(workflow: WorkflowEngine) -> None:
    """注入当前运行的 Workflow 实例（由外部任务启动器调用）。

    注意：不会覆盖已有钩子，而是包装为链式调用。
    """
    global active_workflow
    active_workflow = workflow

    # 保存已有钩子（避免覆盖）
    existing_state_change = workflow.on_state_change
    existing_task_start = workflow.on_task_start
    existing_task_end = workflow.on_task_end

    def on_state_change(state: WorkflowState) -> None:
        if existing_state_change:
            existing_state_change(state)
        try:
            _event_queue.put_nowait({
                "type": "workflow_state_change",
                "data": {"state": state.value},
                "timestamp": time.time(),
            })
        except queue.Full:
            pass

    def on_task_start(task_name: str, node: Node) -> None:
        if existing_task_start:
            existing_task_start(task_name, node)
        try:
            _event_queue.put_nowait({
                "type": "task_started",
                "data": {
                    "task_name": task_name,
                    "agent_id": node.agent_id,
                    "requires_approval": node.requires_approval,
                },
                "timestamp": time.time(),
            })
        except queue.Full:
            pass

    def on_task_end(task_name: str, exec_rec: Any) -> None:
        if existing_task_end:
            existing_task_end(task_name, exec_rec)
        try:
            _event_queue.put_nowait({
                "type": "task_completed",
                "data": {
                    "task_name": task_name,
                    "state": exec_rec.state.value if hasattr(exec_rec, "state") else str(exec_rec.state),
                    "agent_id": exec_rec.agent_id if hasattr(exec_rec, "agent_id") else None,
                    "elapsed": exec_rec.elapsed if hasattr(exec_rec, "elapsed") else 0,
                    "error": exec_rec.error if hasattr(exec_rec, "error") else None,
                    "artifacts": exec_rec.artifacts if hasattr(exec_rec, "artifacts") else [],
                },
                "timestamp": time.time(),
            })
        except queue.Full:
            pass

    workflow.on_state_change = on_state_change
    workflow.on_task_start = on_task_start
    workflow.on_task_end = on_task_end


def inject_hub(new_hub: ContextHub) -> None:
    """替换全局 ContextHub。"""
    global hub
    hub = new_hub
    hub.on_all(_event_handler)


# ── 启动 ──────────────────────────────────────────────────

def run_server(host: str = "0.0.0.0", port: int = 5000, debug: bool = False):
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run_server()
