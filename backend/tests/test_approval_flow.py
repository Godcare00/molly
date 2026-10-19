import pytest
import uuid
from datetime import datetime, timedelta

from app.storage.approvals import create_approval, get_approval, get_approvals, update_approval
from app.storage.conversations import create_conversation
from app.agent.tasks import create_task
from app.security.permissions import ApprovalRecord, ApprovalStatus, permission_engine
from app.security.risk import RiskAssessment


def _unique_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestApprovalPersistence:
    def test_create_and_get_approval(self, conversation_id, task_id):
        approval = ApprovalRecord(
            id=_unique_id("appr"),
            task_id=task_id,
            conversation_id=conversation_id,
            tool_call_id="call_1",
            tool="execute_command",
            arguments={"command": "rm -rf /test"},
            risk_level="DANGEROUS",
            reason="Destructive command",
            status=ApprovalStatus.PENDING,
        )

        create_approval(approval)
        retrieved = get_approval(approval.id)

        assert retrieved is not None
        assert retrieved.id == approval.id
        assert retrieved.tool == "execute_command"
        assert retrieved.risk_level == "DANGEROUS"
        assert retrieved.status == ApprovalStatus.PENDING

    def test_update_approval_status(self, conversation_id, task_id):
        approval = ApprovalRecord(
            id=_unique_id("appr"),
            task_id=task_id,
            conversation_id=conversation_id,
            tool_call_id="call_1",
            tool="execute_command",
            arguments={"command": "rm -rf /test"},
            risk_level="DANGEROUS",
            reason="Destructive command",
            status=ApprovalStatus.PENDING,
        )

        create_approval(approval)

        # Approve
        approval.status = ApprovalStatus.APPROVED
        update_approval(approval)

        retrieved = get_approval(approval.id)
        assert retrieved.status == ApprovalStatus.APPROVED

    def test_list_approvals_by_status(self, conversation_id, task_id):
        # Create multiple approvals
        for i, status in enumerate([ApprovalStatus.PENDING, ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]):
            approval = ApprovalRecord(
                id=_unique_id(f"appr_{i}"),
                task_id=task_id,
                conversation_id=conversation_id,
                tool_call_id=f"call_{i}",
                tool="execute_command",
                arguments={"command": f"cmd_{i}"},
                risk_level="MODERATE",
                reason="Test",
                status=status,
            )
            create_approval(approval)

        pending = get_approvals(status=ApprovalStatus.PENDING)
        assert len(pending) >= 1

        approved = get_approvals(status=ApprovalStatus.APPROVED)
        assert len(approved) >= 1


class TestApprovalStateMachine:
    def test_pending_to_approved_to_completed(self):
        approval = ApprovalRecord(
            id=_unique_id("appr"),
            task_id="task_1",
            conversation_id="conv_1",
            tool_call_id="call_1",
            tool="write_file",
            arguments={"path": "/tmp/test.txt"},
            risk_level="MODERATE",
            reason="File write",
            status=ApprovalStatus.PENDING,
        )

        # Approve
        permission_engine.approve(approval)
        assert approval.status == ApprovalStatus.APPROVED
        assert approval.can_execute()

        # Execute
        permission_engine.start_execution(approval)
        assert approval.status == ApprovalStatus.EXECUTING

        # Complete
        permission_engine.complete_execution(approval, {"success": True})
        assert approval.status == ApprovalStatus.COMPLETED
        assert approval.executed_at is not None

    def test_pending_to_rejected(self):
        approval = ApprovalRecord(
            id=_unique_id("appr"),
            task_id="task_1",
            conversation_id="conv_1",
            tool_call_id="call_1",
            tool="execute_command",
            arguments={"command": "rm -rf /test"},
            risk_level="DANGEROUS",
            reason="Destructive",
            status=ApprovalStatus.PENDING,
        )

        permission_engine.reject(approval)
        assert approval.status == ApprovalStatus.REJECTED
        assert not approval.can_execute()

    def test_pending_to_corrected(self):
        approval = ApprovalRecord(
            id=_unique_id("appr"),
            task_id="task_1",
            conversation_id="conv_1",
            tool_call_id="call_1",
            tool="execute_command",
            arguments={"command": "rm -rf /var/www/mantis"},
            risk_level="DANGEROUS",
            reason="Destructive",
            status=ApprovalStatus.PENDING,
        )

        permission_engine.correct(approval, "Move to /tmp/backup instead")
        assert approval.status == ApprovalStatus.CORRECTED
        assert approval.user_instruction == "Move to /tmp/backup instead"
        assert not approval.can_execute()

    def test_correction_cancels_original(self):
        """Test that correction cancels the original action - it never executes."""
        approval = ApprovalRecord(
            id=_unique_id("appr"),
            task_id="task_1",
            conversation_id="conv_1",
            tool_call_id="call_1",
            tool="execute_command",
            arguments={"command": "rm -rf /var/www/mantis"},
            risk_level="DANGEROUS",
            reason="Destructive",
            status=ApprovalStatus.PENDING,
        )

        # User corrects
        permission_engine.correct(approval, "Don't delete. Move to /tmp/mantis-backup.")

        # Original command should NOT execute
        assert approval.status == ApprovalStatus.CORRECTED
        assert approval.user_instruction == "Don't delete. Move to /tmp/mantis-backup."
        assert not approval.can_execute()

        # The correction creates a NEW approval flow
        # Original is effectively cancelled


class TestApprovalExpiration:
    def test_approval_expiration(self, conversation_id, task_id):
        approval = ApprovalRecord(
            id=_unique_id("appr"),
            task_id=task_id,
            conversation_id=conversation_id,
            tool_call_id="call_1",
            tool="execute_command",
            arguments={"command": "test"},
            risk_level="MODERATE",
            reason="Test",
            status=ApprovalStatus.PENDING,
            expires_at=datetime.utcnow() - timedelta(minutes=1),  # Already expired
        )

        create_approval(approval)

        # In real implementation, a background task would expire these
        # For now, just verify the field exists
        assert approval.expires_at is not None
        assert approval.expires_at < datetime.utcnow()