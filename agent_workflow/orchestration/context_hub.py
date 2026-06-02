"""
ContextHub — 多Agent上下文的中心化监控与干预枢纽。

v3.0 重构 — 退化为纯监控用途:
- 不再强制持有 Conversation 作为唯一来源（每个 Task 使用独立 Conversation）
- 保留事件收集、SQLite 持久化、查询统计等监控能力
- 保留干预机制（基于 session_id 路由）
- 保留跨Agent消息传递
- Agent 注册不再报错重复（允许同名 Task 复用监控槽）

设计理念:
- WorkflowEngine 持有执行逻辑
- ContextHub 持有监控数据
- 两者通过 observer 模式松耦合
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable

from core.llm import Message
from core.memory import Conversation, Snapshot


# ── 事件类型 ────────────────────────────────────────────────────

class ContextEvent:
    """上下文变更事件类型。"""

    AGENT_REGISTERED = "agent_registered"
    AGENT_UNREGISTERED = "agent_unregistered"
    MESSAGE_ADDED = "message_added"
    SYSTEM_UPDATED = "system_updated"
    STEP_RECORDED = "step_recorded"
    SNAPSHOT_CREATED = "snapshot_created"
    ROLLBACK = "rollback"
    INTERVENTION = "intervention"
    AGENT_TO_AGENT = "agent_to_agent"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"


# ── 干预操作 ────────────────────────────────────────────────────

class Intervention:
    """外部干预操作。"""

    def __init__(
        self,
        type: str,  # insert | replace | delete | pause | resume | abort
        target: str,  # session_id
        data: Any = None,
        reason: str | None = None,
    ):
        self.type = type
        self.target = target
        self.data = data
        self.reason = reason
        self.timestamp = time.time()
        self.intervention_id = f"ivn_{uuid.uuid4().hex[:8]}"


# ── ContextHub ──────────────────────────────────────────────────

class ContextHub:
    """
    多Agent上下文监控中枢。

    v3.0 职责收窄:
    1. 事件收集 — 所有 Task 的执行事件持久化到 SQLite
    2. 状态监控 — 查询各 session 的当前状态
    3. 干预路由 — 基于 session_id 的外部干预
    4. 跨Agent消息 — Agent 间通信通道

    不再职责:
    - 持有 Conversation 作为唯一来源（由 WorkflowEngine 管理）
    - 控制执行流程（由 WorkflowEngine 管理）

    使用方式:
        hub = ContextHub()

        # WorkflowEngine 自动注册 Task 的 Conversation 到 Hub
        # Hub 通过 observer 模式接收事件

        # 查询事件
        events = hub.query_events(event_type="task_completed", limit=50)

        # 获取统计
        stats = hub.get_event_stats()

        # 干预（基于 session_id）
        hub.intervene(Intervention(
            type="abort",
            target="coder/develop",
            reason="detected_infinite_loop"
        ))
    """

    def __init__(self, db_path: str | None = None):
        # session 注册表（监控用，不控制生命周期）
        self._sessions: dict[str, Conversation] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

        # 事件监听
        self._listeners: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._global_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._pending_interventions: dict[str, list[Intervention]] = {}

        # SQLite 持久化
        self._db_path = db_path or os.environ.get("DB_PATH", "/tmp/agent_workflow/context_hub.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._db_lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 数据库。"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    agent_id TEXT,
                    data TEXT,
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp)
            """)
            conn.commit()

    def _persist_event(self, event_type: str, agent_id: str | None, data: dict[str, Any]) -> None:
        """持久化事件到 SQLite。"""
        try:
            with self._db_lock, sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO events (event_type, agent_id, data, timestamp) VALUES (?, ?, ?, ?)",
                    (event_type, agent_id, json.dumps(data, ensure_ascii=False), time.time())
                )
                conn.commit()
        except Exception:
            pass

    def query_events(
        self,
        event_type: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """查询历史事件。"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM events WHERE 1=1"
            params: list[Any] = []

            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            if agent_id:
                query += " AND agent_id = ?"
                params.append(agent_id)
            if since:
                query += " AND timestamp >= ?"
                params.append(since)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "id": r["id"],
                    "event_type": r["event_type"],
                    "agent_id": r["agent_id"],
                    "data": json.loads(r["data"]) if r["data"] else {},
                    "timestamp": r["timestamp"],
                }
                for r in rows
            ]

    def get_event_stats(self) -> dict[str, Any]:
        """获取事件统计。"""
        with sqlite3.connect(self._db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            by_type = conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type"
            ).fetchall()
            by_agent = conn.execute(
                "SELECT agent_id, COUNT(*) as cnt FROM events GROUP BY agent_id"
            ).fetchall()

            return {
                "total_events": total,
                "by_type": {r[0]: r[1] for r in by_type},
                "by_agent": {r[0] or "unknown": r[1] for r in by_agent},
            }

    # ── Session 注册（监控用，非强制持有）──────────────────

    def register(self, session_id: str, system_prompt: str | None = None) -> Conversation:
        """
        注册一个 session。

        v3.0 变更:
        - 重复注册不再报错，返回已有 Conversation
        - Conversation 由调用方（WorkflowEngine）管理生命周期
        - Hub 仅用于监控和事件收集
        """
        if session_id in self._sessions:
            return self._sessions[session_id]

        conv = Conversation(session_id=session_id)
        if system_prompt:
            conv.add_system(system_prompt)

        # 安装 observer，将事件转发到 hub
        conv.add_observer(self._create_observer(session_id))

        self._sessions[session_id] = conv
        self._metadata[session_id] = {
            "registered_at": time.time(),
            "session_id": session_id,
        }

        self._emit(ContextEvent.AGENT_REGISTERED, {
            "agent_id": session_id,
            "system_prompt": system_prompt,
        })
        return conv

    def unregister(self, session_id: str) -> bool:
        """注销 session。"""
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        self._metadata.pop(session_id, None)
        self._pending_interventions.pop(session_id, None)
        self._emit(ContextEvent.AGENT_UNREGISTERED, {"agent_id": session_id})
        return True

    def get(self, session_id: str) -> Conversation | None:
        """获取 session 的 Conversation（监控用）。"""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[str]:
        """列出所有已注册的 session ID。"""
        return list(self._sessions.keys())

    def session_summary(self, session_id: str) -> dict[str, Any] | None:
        """获取 session 的状态摘要。"""
        conv = self._sessions.get(session_id)
        if not conv:
            return None
        meta = self._metadata.get(session_id, {})
        return {
            "session_id": session_id,
            "metadata": meta,
            **conv.summary(),
        }

    def all_summaries(self) -> dict[str, dict[str, Any]]:
        """获取所有 session 的状态摘要。"""
        return {sid: self.session_summary(sid) for sid in self._sessions}

    # ── 跨Session消息 ────────────────────────────────────

    def send_to_session(self, from_id: str, to_id: str, content: str) -> bool:
        """从一个 session 向另一个发送消息。"""
        conv = self._sessions.get(to_id)
        if not conv:
            return False
        conv.add_user(f"[Message from {from_id}] {content}")
        self._emit(ContextEvent.AGENT_TO_AGENT, {
            "from": from_id,
            "to": to_id,
            "content": content,
        })
        return True

    def broadcast(self, from_id: str, content: str) -> None:
        """向所有其他 session 广播消息。"""
        for sid in self._sessions:
            if sid != from_id:
                self.send_to_session(from_id, sid, content)

    # ── 干预机制 ──────────────────────────────────────────

    def intervene(self, intervention: Intervention) -> bool:
        """提交干预操作。"""
        conv = self._sessions.get(intervention.target)

        if intervention.type == "insert" and conv:
            data = intervention.data
            msg = Message(role=data.get("role", "system"), content=data.get("content", ""))
            conv.add(msg)

        elif intervention.type == "replace" and conv:
            idx = intervention.data.get("index")
            msg_data = intervention.data.get("message", {})
            if idx is not None and 0 <= idx < conv.message_count:
                new_msg = Message(role=msg_data.get("role", "user"), content=msg_data.get("content", ""))
                conv._messages[idx] = new_msg
                self._emit(ContextEvent.INTERVENTION, {
                    "agent_id": intervention.target,
                    "type": "replace",
                    "index": idx,
                    "intervention_id": intervention.intervention_id,
                })

        elif intervention.type == "delete" and conv:
            idx = intervention.data.get("index")
            if idx is not None and 0 <= idx < conv.message_count:
                del conv._messages[idx]
                self._emit(ContextEvent.INTERVENTION, {
                    "agent_id": intervention.target,
                    "type": "delete",
                    "index": idx,
                    "intervention_id": intervention.intervention_id,
                })

        elif intervention.type in ("pause", "resume", "abort"):
            key = {"pause": "paused", "resume": "paused", "abort": "aborted"}[intervention.type]
            if intervention.target in self._metadata:
                self._metadata[intervention.target][key] = intervention.type != "resume"
            self._emit(ContextEvent.INTERVENTION, {
                "agent_id": intervention.target,
                "type": intervention.type,
                "intervention_id": intervention.intervention_id,
            })

        # 记录干预
        if intervention.target not in self._pending_interventions:
            self._pending_interventions[intervention.target] = []
        self._pending_interventions[intervention.target].append(intervention)

        return True

    def is_paused(self, session_id: str) -> bool:
        return self._metadata.get(session_id, {}).get("paused", False)

    def is_aborted(self, session_id: str) -> bool:
        return self._metadata.get(session_id, {}).get("aborted", False)

    def clear_interventions(self, session_id: str) -> None:
        self._pending_interventions.pop(session_id, None)

    # ── 快照 ──────────────────────────────────────────────

    def snapshot_all(self, metadata: dict[str, Any] | None = None) -> str:
        """创建所有 session 的全局快照。"""
        snapshot_id = f"global_{uuid.uuid4().hex[:8]}"
        global_snap: dict[str, Snapshot] = {}

        for sid, conv in self._sessions.items():
            snap = Snapshot(
                messages=conv.get_messages(),
                steps=conv.get_steps(),
                metadata={"session_id": sid},
            )
            global_snap[sid] = snap

        self._emit(ContextEvent.SNAPSHOT_CREATED, {
            "snapshot_id": snapshot_id,
            "session_count": len(global_snap),
            "metadata": metadata,
        })
        return snapshot_id

    # ── 事件监听 ──────────────────────────────────────────

    def on(self, event_type: str, callback: Callable[[dict[str, Any]], None] | None = None):
        """注册事件监听器（支持装饰器模式）。"""
        def _register(func: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
            if event_type not in self._listeners:
                self._listeners[event_type] = []
            self._listeners[event_type].append(func)
            return func

        if callback is None:
            return _register
        return _register(callback)

    def on_all(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        self._global_listeners.append(callback)

    def off(self, event_type: str, callback: Callable) -> bool:
        if event_type in self._listeners and callback in self._listeners[event_type]:
            self._listeners[event_type].remove(callback)
            return True
        return False

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """发射事件到所有监听器，并持久化到 SQLite。"""
        agent_id = data.get("agent_id")
        self._persist_event(event_type, agent_id, data)

        for cb in self._listeners.get(event_type, []):
            try:
                cb(data)
            except Exception:
                pass
        for cb in self._global_listeners:
            try:
                cb(event_type, data)
            except Exception:
                pass

    def _create_observer(self, session_id: str) -> Callable[[str, dict[str, Any]], None]:
        """为 Conversation 创建 observer 回调。"""
        def observer(event_type: str, data: dict[str, Any]) -> None:
            data["agent_id"] = session_id
            hub_event = self._map_conversation_event(event_type)
            self._emit(hub_event, data)
        return observer

    @staticmethod
    def _map_conversation_event(conv_event: str) -> str:
        mapping = {
            "message_added": ContextEvent.MESSAGE_ADDED,
            "system_updated": ContextEvent.SYSTEM_UPDATED,
            "step_recorded": ContextEvent.STEP_RECORDED,
            "snapshot_created": ContextEvent.SNAPSHOT_CREATED,
            "rollback": ContextEvent.ROLLBACK,
        }
        return mapping.get(conv_event, conv_event)

    # ── 调试 ──────────────────────────────────────────────

    def to_transcript(self, session_id: str) -> str | None:
        conv = self._sessions.get(session_id)
        return conv.to_transcript() if conv else None

    def full_transcript(self) -> str:
        parts: list[str] = []
        for sid in self._sessions:
            t = self.to_transcript(sid)
            if t:
                parts.append(t)
        return "\n\n".join(parts)

    def __repr__(self) -> str:
        return f"ContextHub(sessions={self.list_sessions()})"
