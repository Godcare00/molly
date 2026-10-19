from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Set
from datetime import datetime, timedelta
import uuid

from app.security.risk import classifier, RiskAssessment
from app.tools.registry import RiskLevel


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CORRECTED = "CORRECTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass
class ApprovalRecord:
    id: str
    task_id: str
    conversation_id: str
    tool_call_id: str
    tool: str
    arguments: dict
    risk_level: str
    reason: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    user_instruction: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    execution_result: Optional[dict] = None

    def is_terminal(self) -> bool:
        return self.status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CORRECTED,
            ApprovalStatus.COMPLETED,
            ApprovalStatus.FAILED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.EXPIRED,
        )

    def can_execute(self) -> bool:
        return self.status == ApprovalStatus.APPROVED


class PermissionEngine:
    """Evaluate whether a tool call requires approval and manage the approval flow."""

    def __init__(self, approval_timeout_minutes: int = 30):
        self.approval_timeout_minutes = approval_timeout_minutes

    def evaluate(self, tool_name: str, arguments: dict, cwd: Optional[str] = None) -> RiskAssessment:
        """Evaluate the risk of a tool call."""
        return classifier.classify(tool_name, arguments, cwd)

    def requires_approval(
        self,
        assessment: RiskAssessment,
        allow_all: bool = False,
        trusted_tools: Optional[Set[str]] = None,
        tool_name: Optional[str] = None,
    ) -> bool:
        """Check if a risk assessment requires approval.

        `allow_all` (a per-conversation setting) and `trusted_tools` (a
        per-task set built up via "approve all" during this run) both let
        routine actions skip the prompt. Neither can waive DANGEROUS/CRITICAL
        risk - those always require an explicit approval, so a blanket
        allow-all setting can't accidentally wave through something like a
        destructive shell command.
        """
        if not RiskLevel.requires_approval(assessment.level):
            return False
        if RiskLevel.always_requires_approval(assessment.level):
            return True
        if trusted_tools and tool_name in trusted_tools:
            return False
        if allow_all:
            return False
        return True

    def create_approval(
        self,
        task_id: str,
        conversation_id: str,
        tool_call_id: str,
        tool: str,
        arguments: dict,
        assessment: RiskAssessment,
    ) -> ApprovalRecord:
        """Create a new approval record."""
        expires_at = datetime.utcnow() + timedelta(minutes=self.approval_timeout_minutes)

        return ApprovalRecord(
            id=f"appr_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            tool=tool,
            arguments=arguments,
            risk_level=assessment.level,
            reason=assessment.reason,
            status=ApprovalStatus.PENDING,
            expires_at=expires_at,
        )

    def approve(self, approval: ApprovalRecord) -> ApprovalRecord:
        """Mark approval as approved."""
        approval.status = ApprovalStatus.APPROVED
        approval.updated_at = datetime.utcnow()
        return approval

    def reject(self, approval: ApprovalRecord) -> ApprovalRecord:
        """Mark approval as rejected."""
        approval.status = ApprovalStatus.REJECTED
        approval.updated_at = datetime.utcnow()
        return approval

    def correct(self, approval: ApprovalRecord, instruction: str) -> ApprovalRecord:
        """Mark approval as corrected with user instruction."""
        approval.status = ApprovalStatus.CORRECTED
        approval.user_instruction = instruction
        approval.updated_at = datetime.utcnow()
        return approval

    def start_execution(self, approval: ApprovalRecord) -> ApprovalRecord:
        """Mark approval as executing."""
        approval.status = ApprovalStatus.EXECUTING
        approval.updated_at = datetime.utcnow()
        return approval

    def complete_execution(self, approval: ApprovalRecord, result: dict) -> ApprovalRecord:
        """Mark approval as completed with result."""
        approval.status = ApprovalStatus.COMPLETED
        approval.executed_at = datetime.utcnow()
        approval.execution_result = result
        approval.updated_at = datetime.utcnow()
        return approval

    def fail_execution(self, approval: ApprovalRecord, error: str) -> ApprovalRecord:
        """Mark approval as failed."""
        approval.status = ApprovalStatus.FAILED
        approval.execution_result = {"error": error}
        approval.updated_at = datetime.utcnow()
        return approval

    def cancel(self, approval: ApprovalRecord) -> ApprovalRecord:
        """Cancel a pending approval."""
        approval.status = ApprovalStatus.CANCELLED
        approval.updated_at = datetime.utcnow()
        return approval

    def expire(self, approval: ApprovalRecord) -> ApprovalRecord:
        """Mark approval as expired."""
        approval.status = ApprovalStatus.EXPIRED
        approval.updated_at = datetime.utcnow()
        return approval


# Global permission engine
permission_engine = PermissionEngine()