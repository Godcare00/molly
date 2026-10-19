import json
from pathlib import Path
from typing import Optional
from app.tools.registry import BaseTool, ToolResult, RiskLevel, registry
from app.config import settings
from app.storage.projects import load_project, load_all_projects, Project


class ListProjectsTool(BaseTool):
    name = "list_projects"
    description = "List registered project identifiers and compact metadata."
    risk_level = RiskLevel.READ
    timeout_seconds = 5
    output_limit_chars = 3000

    async def execute(self) -> ToolResult:
        try:
            projects = load_all_projects()
            output = [
                {
                    "id": p.id,
                    "name": p.name,
                    "path": p.path,
                    "environment": p.environment,
                }
                for p in projects
            ]
            return ToolResult(success=True, output={"projects": output, "count": len(output)})
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GetProjectContextTool(BaseTool):
    name = "get_project_context"
    description = "Get compact metadata for a registered project."
    risk_level = RiskLevel.READ
    timeout_seconds = 5
    output_limit_chars = 5000

    async def execute(self, project: str) -> ToolResult:
        try:
            p = load_project(project)
            if not p:
                return ToolResult(success=False, error=f"Project not found: {project}")

            output = {
                "id": p.id,
                "name": p.name,
                "path": p.path,
                "description": p.description,
                "stack": p.stack,
                "repository": p.repository,
                "branch": p.branch,
                "environment": p.environment,
                "services": p.services,
                "commands": p.commands,
                "notes": p.notes,
            }
            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


def register_project_tools():
    registry.register(ListProjectsTool())
    registry.register(GetProjectContextTool())