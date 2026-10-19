import subprocess
import shlex
import os
import signal
from pathlib import Path
from typing import Optional
from app.tools.registry import BaseTool, ToolResult, RiskLevel, registry
from app.security.paths import canonicalize_path, validate_path_safety
from app.config import settings


class ExecuteCommandTool(BaseTool):
    name = "execute_command"
    description = "Execute arbitrary shell commands. Subject to approval, timeout, and resource limits."
    risk_level = RiskLevel.HIGH_RISK  # Default, actual risk classified dynamically
    timeout_seconds = 120
    output_limit_chars = 10000

    async def execute(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
    ) -> ToolResult:
        try:
            # Resolve working directory
            if cwd:
                safe_cwd = canonicalize_path(cwd)
                validate_path_safety(safe_cwd)
                if not safe_cwd.exists() or not safe_cwd.is_dir():
                    return ToolResult(success=False, error=f"Working directory does not exist: {cwd}")
            else:
                safe_cwd = Path.cwd()

            # Prepare environment
            cmd_env = os.environ.copy()
            if env:
                cmd_env.update(env)

            # Execute with timeout
            exec_timeout = timeout or settings.max_command_timeout_seconds

            process = subprocess.Popen(
                command,
                shell=True,
                cwd=safe_cwd,
                env=cmd_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid,  # Create process group for cleanup
            )

            try:
                stdout, stderr = process.communicate(timeout=exec_timeout)
                return_code = process.returncode
            except subprocess.TimeoutExpired:
                # Kill the entire process group
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                stdout, stderr = process.communicate()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {exec_timeout} seconds",
                    output={"stdout": stdout, "stderr": stderr, "return_code": -1, "timed_out": True},
                )

            # Truncate output if needed
            max_chars = self.output_limit_chars
            truncated = False

            if len(stdout) > max_chars:
                stdout = stdout[:max_chars] + f"\n... [truncated, {len(stdout)} total chars]"
                truncated = True
            if len(stderr) > max_chars:
                stderr = stderr[:max_chars] + f"\n... [truncated, {len(stderr)} total chars]"
                truncated = True

            return ToolResult(
                success=return_code == 0,
                output={
                    "stdout": stdout,
                    "stderr": stderr,
                    "return_code": return_code,
                    "command": command,
                    "cwd": str(safe_cwd),
                },
                truncated=truncated,
                metadata={"resolved_cwd": str(safe_cwd)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


def register_terminal_tools():
    registry.register(ExecuteCommandTool())