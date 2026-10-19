import pytest
from pathlib import Path

from app.security.paths import canonicalize_path, validate_path_safety, is_within, get_safe_temp_path
from app.security.risk import classifier, RiskLevel
from app.security.permissions import permission_engine, ApprovalStatus, ApprovalRecord


class TestPathHandling:
    def test_canonicalize_path(self):
        # Test relative path
        result = canonicalize_path(".")
        assert result.is_absolute()

    def test_canonicalize_expands_user(self):
        result = canonicalize_path("~/test")
        assert str(result).startswith("/home/") or str(result).startswith("/root/")

    def test_validate_path_safety_null_bytes(self):
        with pytest.raises(ValueError, match="null bytes"):
            validate_path_safety(Path("/test\x00path"))

    def test_validate_path_safety_traversal(self):
        # This should pass - we allow absolute paths anywhere
        validate_path_safety(Path("/etc/passwd"))

    def test_is_within(self):
        parent = Path("/home/user")
        child = Path("/home/user/project")
        assert is_within(child, parent)

        outside = Path("/etc")
        assert not is_within(outside, parent)

    def test_get_safe_temp_path(self):
        base = Path("/tmp/test")
        path = get_safe_temp_path(base, "prefix_")
        assert path.parent == base
        assert path.name.startswith("prefix_")


class TestRiskClassifier:
    @pytest.mark.asyncio
    async def test_read_only_tools(self):
        tools = [
            "get_system_info",
            "get_disk_usage",
            "get_memory_usage",
            "get_processes",
            "get_service_status",
            "list_directory",
            "search_files",
            "read_file",
            "git_status",
            "git_diff",
            "git_log",
            "list_projects",
            "get_project_context",
            "view_image",
        ]
        for tool in tools:
            assessment = classifier.classify(tool, {})
            assert assessment.level == RiskLevel.READ

    @pytest.mark.asyncio
    async def test_write_file_risk(self):
        # File writes no longer require approval - only destructive commands do.
        assessment = classifier.classify("write_file", {"path": "/tmp/test.txt"})
        assert assessment.level == RiskLevel.LOW_RISK

    @pytest.mark.asyncio
    async def test_edit_file_risk(self):
        assessment = classifier.classify("edit_file", {"path": "/tmp/test.txt", "operation": "replace"})
        assert assessment.level == RiskLevel.LOW_RISK

    @pytest.mark.asyncio
    async def test_execute_command_destructive(self):
        assessment = classifier.classify("execute_command", {"command": "rm -rf /var/www/mantis"})
        assert assessment.level == RiskLevel.DANGEROUS

    @pytest.mark.asyncio
    async def test_execute_command_sudo(self):
        assessment = classifier.classify("execute_command", {"command": "sudo systemctl restart nginx"})
        assert assessment.level == RiskLevel.HIGH_RISK

    @pytest.mark.asyncio
    async def test_execute_command_production_path(self):
        assessment = classifier.classify(
            "execute_command",
            {"command": "ls", "cwd": "/var/www/mantis"}
        )
        assert assessment.level == RiskLevel.MODERATE

    @pytest.mark.asyncio
    async def test_execute_command_sensitive_path(self):
        assessment = classifier.classify(
            "execute_command",
            {"command": "cat /etc/shadow"}
        )
        assert assessment.level == RiskLevel.HIGH_RISK


class TestPermissionEngine:
    def test_requires_approval_read(self):
        from app.security.risk import RiskAssessment
        assessment = RiskAssessment(RiskLevel.READ, "read", [])
        assert not permission_engine.requires_approval(assessment)

    def test_requires_approval_moderate(self):
        from app.security.risk import RiskAssessment
        assessment = RiskAssessment(RiskLevel.MODERATE, "moderate", [])
        assert permission_engine.requires_approval(assessment)

    def test_requires_approval_dangerous(self):
        from app.security.risk import RiskAssessment
        assessment = RiskAssessment(RiskLevel.DANGEROUS, "dangerous", [])
        assert permission_engine.requires_approval(assessment)

    def test_create_approval(self):
        from app.security.risk import RiskAssessment
        assessment = RiskAssessment(RiskLevel.DANGEROUS, "test reason", ["factor1"])
        approval = permission_engine.create_approval(
            task_id="task_1",
            conversation_id="conv_1",
            tool_call_id="call_1",
            tool="execute_command",
            arguments={"command": "rm -rf /test"},
            assessment=assessment,
        )
        assert approval.status == ApprovalStatus.PENDING
        assert approval.risk_level == RiskLevel.DANGEROUS
        assert approval.reason == "test reason"

    def test_approval_state_transitions(self):
        from app.security.risk import RiskAssessment
        assessment = RiskAssessment(RiskLevel.MODERATE, "test", [])
        approval = permission_engine.create_approval(
            task_id="task_1",
            conversation_id="conv_1",
            tool_call_id="call_1",
            tool="write_file",
            arguments={"path": "/tmp/test.txt"},
            assessment=assessment,
        )

        # Approve
        permission_engine.approve(approval)
        assert approval.status == ApprovalStatus.APPROVED

        # Reject (new approval)
        approval2 = permission_engine.create_approval(
            task_id="task_1",
            conversation_id="conv_1",
            tool_call_id="call_2",
            tool="write_file",
            arguments={"path": "/tmp/test2.txt"},
            assessment=assessment,
        )
        permission_engine.reject(approval2)
        assert approval2.status == ApprovalStatus.REJECTED

        # Correct
        approval3 = permission_engine.create_approval(
            task_id="task_1",
            conversation_id="conv_1",
            tool_call_id="call_3",
            tool="write_file",
            arguments={"path": "/tmp/test3.txt"},
            assessment=assessment,
        )
        permission_engine.correct(approval3, "Use /tmp/safe.txt instead")
        assert approval3.status == ApprovalStatus.CORRECTED
        assert approval3.user_instruction == "Use /tmp/safe.txt instead"