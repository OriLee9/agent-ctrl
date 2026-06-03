"""Structured review tools for review_gate workflow.

Provides a `review_decision` tool that reviewer agents MUST call
instead of writing free-text approval/rejection.

Usage:
    from core.review_tools import review_decision_tool, reviewer_system_prompt
    agent.register_tool(review_decision_tool())
    agent.system_prompt = reviewer_system_prompt("game code")
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.tool import Tool, ToolResult, tool


@dataclass
class ReviewDecision:
    """Structured review decision."""

    approved: bool
    feedback: str
    severity: str = "minor"  # minor | major | critical
    suggestions: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "feedback": self.feedback,
            "severity": self.severity,
            "suggestions": self.suggestions or [],
        }

    @classmethod
    def from_tool_result(cls, result: Any) -> "ReviewDecision | None":
        """Parse a tool result into ReviewDecision."""
        if isinstance(result, dict):
            return cls(
                approved=bool(result.get("approved", False)),
                feedback=str(result.get("feedback", "")),
                severity=str(result.get("severity", "minor")),
                suggestions=result.get("suggestions") or [],
            )
        return None


# Global store: task_name -> latest ReviewDecision
# This is used by WorkflowEngine to read the decision after reviewer finishes.
_review_decisions: dict[str, ReviewDecision] = {}


def get_review_decision(task_name: str) -> ReviewDecision | None:
    """Get the latest review decision for a task."""
    return _review_decisions.get(task_name)


def set_review_decision(task_name: str, decision: ReviewDecision) -> None:
    """Store a review decision for a task."""
    _review_decisions[task_name] = decision


def clear_review_decision(task_name: str) -> None:
    """Clear the review decision for a task (e.g. before re-run)."""
    _review_decisions.pop(task_name, None)


def review_decision_tool() -> Tool:
    """Create the review_decision tool.

    Reviewer agents MUST call this tool at the end of their review
    to produce a structured decision.
    """
    @tool
    def review_decision(
        approved: bool,
        feedback: str,
        severity: str = "minor",
        suggestions: str = "",
    ) -> dict[str, Any]:
        """Submit your structured review decision.

        YOU MUST CALL THIS TOOL at the end of your review.
        Do NOT write free-text approval — use this tool instead.

        Args:
            approved: True if the implementation meets all requirements and can be accepted.
                      False if there are issues that need to be fixed.
            feedback: Detailed review feedback. Explain what is good, what needs improvement,
                      and specific actionable suggestions.
            severity: "minor" (cosmetic, style), "major" (functional issues), or "critical" (broken).
            suggestions: JSON array string of specific improvement suggestions.
                         Example: '["Fix the variable name on line 23", "Add error handling"]'
        """
        suggestion_list: list[str] = []
        if suggestions:
            import json as _json
            try:
                parsed = _json.loads(suggestions)
                if isinstance(parsed, list):
                    suggestion_list = [str(s) for s in parsed]
            except Exception:
                suggestion_list = [suggestions]

        decision = ReviewDecision(
            approved=approved,
            feedback=feedback,
            severity=severity,
            suggestions=suggestion_list,
        )
        # Store for WorkflowEngine to read
        # We use a sentinel key pattern because we don't know the task name here.
        # WorkflowEngine will read the result from the tool output itself.
        return {
            "result": "Review submitted",
            "_review_decision": decision.to_dict(),
        }

    return review_decision


def reviewer_system_prompt(what: str = "implementation") -> str:
    """Return a system prompt for a reviewer agent.

    This prompt instructs the agent to use the review_decision tool.
    """
    return (
        f"You are a meticulous reviewer. Your job is to review the {what} "
        f"produced by another agent and decide whether it is acceptable.\n\n"
        f"CRITICAL: At the end of your review, you MUST call the `review_decision` tool "
        f"with a structured decision. Do NOT write free-text approval.\n\n"
        f"Guidelines:\n"
        f"1. Check correctness, completeness, and quality\n"
        f"2. Provide specific, actionable feedback\n"
        f"3. Call `review_decision(approved=True, ...)` only if everything is correct\n"
        f"4. Call `review_decision(approved=False, ...)` if ANY issue exists\n"
    )
