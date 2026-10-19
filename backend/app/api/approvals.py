from fastapi import APIRouter, HTTPException, Body, Depends
from typing import Optional
from pydantic import BaseModel

from app.storage.approvals import get_approval, get_approvals, update_approval
from app.security.permissions import permission_engine, ApprovalStatus
from app.agent.executor import AgentExecutor
from app.agent.tasks import get_task
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/approvals", tags=["approvals"], dependencies=[Depends(get_current_user)])


class ApproveRequest(BaseModel):
    pass


class RejectRequest(BaseModel):
    pass


class CorrectRequest(BaseModel):
    instruction: str


@router.get("")
async def list_approvals(
    conversation_id: Optional[str] = None,
    task_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """List approvals with optional filters."""
    status_enum = None
    if status:
        try:
            status_enum = ApprovalStatus(status.upper())
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    approvals = get_approvals(conversation_id, task_id, status_enum, limit)
    return [
        {
            "id": a.id,
            "task_id": a.task_id,
            "conversation_id": a.conversation_id,
            "tool": a.tool,
            "arguments": a.arguments,
            "risk_level": a.risk_level,
            "reason": a.reason,
            "status": a.status.value,
            "user_instruction": a.user_instruction,
            "created_at": a.created_at.isoformat(),
            "updated_at": a.updated_at.isoformat(),
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        }
        for a in approvals
    ]


@router.get("/{approval_id}")
async def get_approval_detail(approval_id: str):
    """Get approval details."""
    approval = get_approval(approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")

    return {
        "id": approval.id,
        "task_id": approval.task_id,
        "conversation_id": approval.conversation_id,
        "tool_call_id": approval.tool_call_id,
        "tool": approval.tool,
        "arguments": approval.arguments,
        "risk_level": approval.risk_level,
        "reason": approval.reason,
        "status": approval.status.value,
        "user_instruction": approval.user_instruction,
        "created_at": approval.created_at.isoformat(),
        "updated_at": approval.updated_at.isoformat(),
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        "executed_at": approval.executed_at.isoformat() if approval.executed_at else None,
        "execution_result": approval.execution_result,
    }


@router.post("/{approval_id}/approve")
async def approve(approval_id: str):
    """Approve a pending action."""
    approval = get_approval(approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(400, f"Approval is not pending: {approval.status.value}")

    # Update approval
    updated = permission_engine.approve(approval)
    update_approval(updated)

    # Notify agent executor if waiting
    # This would need a way to find the running executor
    # For now, we just update the database

    return {"status": "approved", "approval_id": approval_id}


@router.post("/{approval_id}/reject")
async def reject(approval_id: str):
    """Reject a pending action."""
    approval = get_approval(approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(400, f"Approval is not pending: {approval.status.value}")

    updated = permission_engine.reject(approval)
    update_approval(updated)

    return {"status": "rejected", "approval_id": approval_id}


@router.post("/{approval_id}/correct")
async def correct(approval_id: str, request: CorrectRequest):
    """Correct a pending action with user instruction."""
    approval = get_approval(approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(400, f"Approval is not pending: {approval.status.value}")

    updated = permission_engine.correct(approval, request.instruction)
    update_approval(updated)

    return {"status": "corrected", "approval_id": approval_id, "instruction": request.instruction}