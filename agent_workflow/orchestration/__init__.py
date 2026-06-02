"""
Orchestration layer — multi-agent coordination & workflow DAG.

- ContextHub: Centralized context monitoring & intervention
- Task: Task definition with template variables
- WorkflowEngine: DAG execution + checkpoint + approval + retry
"""

from orchestration.context_hub import ContextHub, ContextEvent, Intervention
from orchestration.rules import RuleConfig, SimpleRuleEngine
from orchestration.task import Task
from orchestration.workflow import (
    Node,
    TaskExecution,
    TaskResult,
    TaskState,
    Workflow,
    WorkflowCheckpoint,
    WorkflowEngine,
    WorkflowExecution,
    WorkflowResult,
    WorkflowState,
    sequential_workflow,
    parallel_workflow,
    mapreduce_workflow,
    conditional_workflow,
    run_chain,
)

__all__ = [
    # Context
    "ContextHub",
    "ContextEvent",
    "Intervention",
    # Rules
    "RuleConfig",
    "SimpleRuleEngine",
    # Task
    "Task",
    # Workflow
    "Workflow",
    "WorkflowEngine",
    "Node",
    "TaskResult",
    "WorkflowResult",
    "TaskExecution",
    "TaskState",
    "WorkflowExecution",
    "WorkflowState",
    "WorkflowCheckpoint",
    # Presets
    "sequential_workflow",
    "parallel_workflow",
    "mapreduce_workflow",
    "conditional_workflow",
    "run_chain",
]
