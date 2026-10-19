import subprocess
from pathlib import Path
from typing import Optional
from app.tools.registry import BaseTool, ToolResult, RiskLevel, registry
from app.security.paths import canonicalize_path, validate_path_safety


def _run_git(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command."""
    return subprocess.run(
        ["git", "-C", str(cwd)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class GitStatusTool(BaseTool):
    name = "git_status"
    description = "Get compact Git status information for a repository."
    risk_level = RiskLevel.READ
    timeout_seconds = 15
    output_limit_chars = 5000

    async def execute(self, path: str) -> ToolResult:
        try:
            safe_path = canonicalize_path(path)
            validate_path_safety(safe_path)

            if not safe_path.exists():
                return ToolResult(success=False, error=f"Path does not exist: {path}")

            # Check if it's a git repo
            result = _run_git(["rev-parse", "--git-dir"], safe_path)
            if result.returncode != 0:
                return ToolResult(success=False, error=f"Not a git repository: {path}")

            # Get status
            result = _run_git(["status", "--porcelain=v1", "-b"], safe_path)

            output = {
                "path": str(safe_path),
                "branch": "",
                "ahead": 0,
                "behind": 0,
                "staged": [],
                "unstaged": [],
                "untracked": [],
            }

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                if line.startswith("##"):
                    # Branch info: ## branch...origin/branch [ahead 1, behind 2]
                    parts = line[3:].split()
                    output["branch"] = parts[0] if parts else ""
                    for part in parts[1:]:
                        if part.startswith("[ahead"):
                            output["ahead"] = int(part.split()[1].rstrip("]"))
                        elif part.startswith("behind"):
                            output["behind"] = int(part.split()[1].rstrip("]"))
                else:
                    status = line[:2]
                    filepath = line[3:]
                    if status[0] != " ":
                        output["staged"].append({"status": status[0], "file": filepath})
                    if status[1] != " ":
                        output["unstaged"].append({"status": status[1], "file": filepath})
                    if status == "??":
                        output["untracked"].append(filepath)

            return ToolResult(success=True, output=output)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Git command timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = "Get bounded relevant Git diff information. Does not dump massive diffs."
    risk_level = RiskLevel.READ
    timeout_seconds = 15
    output_limit_chars = 15000

    async def execute(self, path: str, staged: bool = False, max_chars: Optional[int] = None) -> ToolResult:
        try:
            safe_path = canonicalize_path(path)
            validate_path_safety(safe_path)

            if not safe_path.exists():
                return ToolResult(success=False, error=f"Path does not exist: {path}")

            result = _run_git(["rev-parse", "--git-dir"], safe_path)
            if result.returncode != 0:
                return ToolResult(success=False, error=f"Not a git repository: {path}")

            args = ["diff"]
            if staged:
                args.append("--cached")

            result = _run_git(args, safe_path)

            max_chars = max_chars or self.output_limit_chars
            diff_output = result.stdout

            truncated = len(diff_output) > max_chars
            if truncated:
                diff_output = diff_output[:max_chars] + f"\n... [truncated, {len(diff_output)} total chars]"

            # Parse file count
            files_changed = diff_output.count("diff --git")

            return ToolResult(
                success=True,
                output={
                    "path": str(safe_path),
                    "staged": staged,
                    "diff": diff_output,
                    "files_changed": files_changed,
                },
                truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Git command timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GitLogTool(BaseTool):
    name = "git_log"
    description = "Get recent commit history. Keeps output compact."
    risk_level = RiskLevel.READ
    timeout_seconds = 15
    output_limit_chars = 8000

    async def execute(self, path: str, limit: int = 10, oneline: bool = True) -> ToolResult:
        try:
            safe_path = canonicalize_path(path)
            validate_path_safety(safe_path)

            if not safe_path.exists():
                return ToolResult(success=False, error=f"Path does not exist: {path}")

            result = _run_git(["rev-parse", "--git-dir"], safe_path)
            if result.returncode != 0:
                return ToolResult(success=False, error=f"Not a git repository: {path}")

            args = ["log", f"-{limit}"]
            if oneline:
                args.append("--oneline")
            else:
                args.extend(["--pretty=format:%H|%an|%ad|%s", "--date=short"])

            result = _run_git(args, safe_path)

            commits = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                if oneline:
                    parts = line.split(" ", 1)
                    commits.append({"hash": parts[0], "message": parts[1] if len(parts) > 1 else ""})
                else:
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        commits.append(
                            {"hash": parts[0], "author": parts[1], "date": parts[2], "message": parts[3]}
                        )

            return ToolResult(
                success=True,
                output={"path": str(safe_path), "commits": commits, "count": len(commits)},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Git command timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


def register_git_tools():
    registry.register(GitStatusTool())
    registry.register(GitDiffTool())
    registry.register(GitLogTool())