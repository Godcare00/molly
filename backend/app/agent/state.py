from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
import uuid


class TaskStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"  # blocked on an ask_user questionnaire


@dataclass
class ToolCallState:
    id: str
    tool_name: str
    arguments: Dict[str, Any]
    status: str = "pending"  # pending, executing, completed, failed
    result: Optional[Any] = None
    error: Optional[str] = None
    approval_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class AgentState:
    """Current state of an agent run."""
    task_id: str
    conversation_id: str
    status: TaskStatus = TaskStatus.RUNNING
    iterations: int = 0
    tool_calls: List[ToolCallState] = field(default_factory=list)
    current_tool_call: Optional[ToolCallState] = None
    pending_approval_id: Optional[str] = None
    pending_questionnaire_id: Optional[str] = None
    error: Optional[str] = None
    final_response: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> ToolCallState:
        call = ToolCallState(
            id=f"call_{uuid.uuid4().hex[:8]}",
            tool_name=tool_name,
            arguments=arguments,
        )
        self.tool_calls.append(call)
        self.current_tool_call = call
        self.iterations += 1
        self.updated_at = datetime.utcnow()
        return call

    def complete_tool_call(self, call_id: str, result: Any, error: str = None) -> None:
        for call in self.tool_calls:
            if call.id == call_id:
                call.status = "failed" if error else "completed"
                call.result = result
                call.error = error
                call.completed_at = datetime.utcnow()
                break
        self.current_tool_call = None
        self.updated_at = datetime.utcnow()

    def set_waiting_approval(self, approval_id: str) -> None:
        self.status = TaskStatus.WAITING_APPROVAL
        self.pending_approval_id = approval_id
        self.updated_at = datetime.utcnow()

    def resume_from_approval(self, approval_id: str, approved: bool, correction: str = None) -> None:
        self.status = TaskStatus.RUNNING
        self.pending_approval_id = None
        self.updated_at = datetime.utcnow()

    def set_waiting_questionnaire(self, questionnaire_id: str) -> None:
        self.status = TaskStatus.WAITING_INPUT
        self.pending_questionnaire_id = questionnaire_id
        self.updated_at = datetime.utcnow()

    def resume_from_questionnaire(self, questionnaire_id: str) -> None:
        self.status = TaskStatus.RUNNING
        self.pending_questionnaire_id = None
        self.updated_at = datetime.utcnow()

    def complete(self, final_response: str) -> None:
        self.status = TaskStatus.COMPLETED
        self.final_response = final_response
        self.updated_at = datetime.utcnow()

    def fail(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.error = error
        self.updated_at = datetime.utcnow()

    def cancel(self) -> None:
        self.status = TaskStatus.CANCELLED
        self.updated_at = datetime.utcnow()

    def is_terminal(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "conversation_id": self.conversation_id,
            "status": self.status.value,
            "iterations": self.iterations,
            "tool_calls_count": len(self.tool_calls),
            "pending_approval_id": self.pending_approval_id,
            "error": self.error,
            "final_response": self.final_response,
        }