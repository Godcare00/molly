import re
from dataclasses import dataclass
from typing import Optional
from app.tools.registry import RiskLevel
from app.security.paths import canonicalize_path


@dataclass
class RiskAssessment:
    level: str
    reason: str
    factors: list[str]


class RiskClassifier:
    """Classify the risk level of a tool call."""

    # Dangerous command patterns
    DESTRUCTIVE_COMMANDS = [
        r"\brm\s+(-rf?|--recursive|--force)",
        r"\bdd\s+",
        r"\bmkfs\b",
        r"\bformat\b",
        r">\s*/dev/",
        r":(){ :|:& };:",  # fork bomb
        r"\bchmod\s+[-+]?\s*[0-7]*[0-7][0-7]\s+/",
        r"\bchown\s+[-R]+\s+/",
    ]

    HIGH_IMPACT_COMMANDS = [
        r"\bsystemctl\s+(stop|restart|disable|mask)\s+",
        r"\bservice\s+\w+\s+(stop|restart)",
        r"\bdocker\s+(stop|rm|kill|prune)",
        r"\bkubectl\s+(delete|drain)",
        r"\bapt\s+(remove|purge|autoremove)",
        r"\byum\s+remove",
        r"\bpip\s+uninstall",
        r"\bnpm\s+uninstall",
    ]

    MODERATE_COMMANDS = [
        r"\bsystemctl\s+(start|enable|reload)",
        r"\bservice\s+\w+\s+start",
        r"\bdocker\s+(start|restart)",
        r"\bapt\s+(install|update|upgrade)",
        r"\bpip\s+install",
        r"\bnpm\s+install",
        r"\bmake\b",
        r"\bcmake\b",
        r"\bgcc\b",
        r"\bcargo\s+build",
        r"\bgo\s+build",
    ]

    SENSITIVE_PATHS = [
        "/etc/passwd",
        "/etc/shadow",
        "/etc/sudoers",
        "/etc/ssh/",
        "/root/.ssh/",
        "/home/*/.ssh/",
        "/etc/ssl/",
        "/etc/certificates/",
        "/var/lib/docker/",
        "/var/lib/kubelet/",
    ]

    PRODUCTION_PATHS = [
        "/var/www/",
        "/opt/",
        "/srv/",
        "/usr/local/bin/",
        "/etc/nginx/",
        "/etc/apache2/",
        "/etc/systemd/",
    ]

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        self.destructive_patterns = [re.compile(p) for p in self.DESTRUCTIVE_COMMANDS]
        self.high_impact_patterns = [re.compile(p) for p in self.HIGH_IMPACT_COMMANDS]
        self.moderate_patterns = [re.compile(p) for p in self.MODERATE_COMMANDS]

    def classify(self, tool_name: str, arguments: dict, cwd: Optional[str] = None) -> RiskAssessment:
        """Classify risk based on tool, arguments, and context."""
        factors = []

        # Tool-specific classification
        if tool_name == "execute_command":
            return self._classify_command(arguments, cwd, factors)
        elif tool_name == "write_file":
            return self._classify_write_file(arguments, factors)
        elif tool_name == "edit_file":
            return self._classify_edit_file(arguments, factors)
        elif tool_name in ("get_service_status", "git_status", "git_diff", "git_log", "list_directory", "search_files", "read_file"):
            return RiskAssessment(RiskLevel.READ, "Read-only operation", ["read_only"])
        elif tool_name in ("list_projects", "get_project_context", "get_system_info", "get_disk_usage", "get_memory_usage", "get_processes", "view_image"):
            return RiskAssessment(RiskLevel.READ, "Read-only system info", ["read_only"])

        # Default
        return RiskAssessment(RiskLevel.LOW_RISK, "Default low risk", ["default"])

    def _classify_command(self, arguments: dict, cwd: Optional[str], factors: list[str]) -> RiskAssessment:
        command = arguments.get("command", "").strip()
        working_dir = cwd or arguments.get("cwd", "")

        if not command:
            return RiskAssessment(RiskLevel.LOW_RISK, "Empty command", ["empty"])

        cmd_lower = command.lower()

        # Check for destructive patterns
        for pattern in self.destructive_patterns:
            if pattern.search(cmd_lower):
                factors.append("destructive_command")
                return RiskAssessment(
                    RiskLevel.DANGEROUS,
                    f"Command matches destructive pattern: {pattern.pattern}",
                    factors,
                )

        # Check for high impact patterns
        for pattern in self.high_impact_patterns:
            if pattern.search(cmd_lower):
                factors.append("high_impact_command")
                return RiskAssessment(
                    RiskLevel.HIGH_RISK,
                    f"Command has high system impact: {pattern.pattern}",
                    factors,
                )

        # Check for moderate patterns
        for pattern in self.moderate_patterns:
            if pattern.search(cmd_lower):
                factors.append("moderate_command")
                return RiskAssessment(
                    RiskLevel.MODERATE,
                    f"Command modifies system state: {pattern.pattern}",
                    factors,
                )

        # Check for sensitive paths in command
        for sensitive in self.SENSITIVE_PATHS:
            if sensitive in command:
                factors.append("sensitive_path")
                return RiskAssessment(
                    RiskLevel.HIGH_RISK,
                    f"Command references sensitive path: {sensitive}",
                    factors,
                )

        # Check working directory for production paths
        if working_dir:
            for prod_path in self.PRODUCTION_PATHS:
                if working_dir.startswith(prod_path):
                    factors.append("production_directory")
                    return RiskAssessment(
                        RiskLevel.MODERATE,
                        f"Command runs in production directory: {working_dir}",
                        factors,
                    )

        # Check for sudo
        if cmd_lower.startswith("sudo ") or " sudo " in cmd_lower:
            factors.append("privileged")
            return RiskAssessment(
                RiskLevel.HIGH_RISK,
                "Command uses sudo/privileged execution",
                factors,
            )

        # Check for pipes to bash/sh
        if re.search(r"\|\s*(bash|sh|zsh|fish)\b", cmd_lower):
            factors.append("pipe_to_shell")
            return RiskAssessment(
                RiskLevel.HIGH_RISK,
                "Command pipes to shell interpreter",
                factors,
            )

        # Default for execute_command
        factors.append("generic_command")
        return RiskAssessment(RiskLevel.MODERATE, "Generic command execution", factors)

    def _classify_write_file(self, arguments: dict, factors: list[str]) -> RiskAssessment:
        path = arguments.get("path", "")

        # File writes/edits no longer gate on approval at all (see
        # _classify_edit_file below and PermissionEngine.requires_approval) -
        # approval is reserved for destructive commands. Sensitive/production
        # path still gets tagged in `factors` for the audit trail even though
        # it no longer changes the risk level.
        for sensitive in self.SENSITIVE_PATHS:
            if path.startswith(sensitive):
                factors.append("sensitive_path")
                return RiskAssessment(
                    RiskLevel.LOW_RISK,
                    f"Writing to sensitive path: {sensitive}",
                    factors,
                )

        for prod_path in self.PRODUCTION_PATHS:
            if path.startswith(prod_path):
                factors.append("production_path")
                return RiskAssessment(
                    RiskLevel.LOW_RISK,
                    f"Writing to production path: {path}",
                    factors,
                )

        factors.append("file_write")
        return RiskAssessment(RiskLevel.LOW_RISK, "File write operation", factors)

    def _classify_edit_file(self, arguments: dict, factors: list[str]) -> RiskAssessment:
        path = arguments.get("path", "")

        for sensitive in self.SENSITIVE_PATHS:
            if path.startswith(sensitive):
                factors.append("sensitive_path")
                return RiskAssessment(
                    RiskLevel.LOW_RISK,
                    f"Editing sensitive path: {sensitive}",
                    factors,
                )

        factors.append("file_edit")
        return RiskAssessment(RiskLevel.LOW_RISK, "File edit operation", factors)


# Global classifier instance
classifier = RiskClassifier()