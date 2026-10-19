from app.tools.registry import registry, ToolResult, RiskLevel, ToolSchema, ToolParameter, BaseTool

# Import all tool modules to trigger registration
from app.tools import system, filesystem, terminal, git, projects, vision, sharing, skills, questionnaire

# Register all tools
system.register_system_tools()
filesystem.register_filesystem_tools()
terminal.register_terminal_tools()
git.register_git_tools()
projects.register_project_tools()
vision.register_vision_tools()
sharing.register_sharing_tools()
skills.register_skills_tools()
questionnaire.register_questionnaire_tools()

__all__ = [
    "registry",
    "ToolResult",
    "RiskLevel",
    "ToolSchema",
    "ToolParameter",
    "BaseTool",
]