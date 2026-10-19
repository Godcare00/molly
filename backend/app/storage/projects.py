import json
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, asdict
from app.storage.database import execute_query, execute_write
from app.config import settings


@dataclass
class Project:
    id: str
    name: str
    path: str
    description: str = ""
    stack: List[str] = None
    repository: str = ""
    branch: str = "main"
    environment: str = "development"
    services: List[str] = None
    commands: dict = None
    notes: List[str] = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if self.stack is None:
            self.stack = []
        if self.services is None:
            self.services = []
        if self.commands is None:
            self.commands = {}
        if self.notes is None:
            self.notes = []

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "description": self.description,
            "stack": self.stack,
            "repository": self.repository,
            "branch": self.branch,
            "environment": self.environment,
            "services": self.services,
            "commands": self.commands,
            "notes": self.notes,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Project":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            path=data.get("path", ""),
            description=data.get("description", ""),
            stack=data.get("stack", []),
            repository=data.get("repository", ""),
            branch=data.get("branch", "main"),
            environment=data.get("environment", "development"),
            services=data.get("services", []),
            commands=data.get("commands", {}),
            notes=data.get("notes", []),
        )

    @classmethod
    def from_row(cls, row) -> "Project":
        return cls(
            id=row["id"],
            name=row["name"],
            path=row["path"],
            description=row["description"] or "",
            stack=json.loads(row["stack"] or "[]"),
            repository=row["repository"] or "",
            branch=row["branch"] or "main",
            environment=row["environment"] or "development",
            services=json.loads(row["services"] or "[]"),
            commands=json.loads(row["commands"] or "{}"),
            notes=json.loads(row["notes"] or "[]"),
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )


def load_project(project_id: str) -> Optional[Project]:
    # First check database
    rows = execute_query("SELECT * FROM projects WHERE id = ?", (project_id,))
    if rows:
        return Project.from_row(rows[0])

    # Fallback to JSON file
    json_path = settings.projects_path / f"{project_id}.json"
    if json_path.exists():
        with open(json_path) as f:
            data = json.load(f)
        return Project.from_json(data)

    return None


def load_all_projects() -> List[Project]:
    projects = []

    # Load from database
    rows = execute_query("SELECT * FROM projects ORDER BY name")
    for row in rows:
        projects.append(Project.from_row(row))

    # Load from JSON files (for backward compatibility)
    if settings.projects_path.exists():
        for json_file in settings.projects_path.glob("*.json"):
            project_id = json_file.stem
            # Skip if already loaded from DB
            if not any(p.id == project_id for p in projects):
                with open(json_file) as f:
                    data = json.load(f)
                projects.append(Project.from_json(data))

    return projects


def save_project(project: Project) -> Project:
    """Save project to both database and JSON file."""
    from datetime import datetime

    now = datetime.utcnow().isoformat()
    project.updated_at = now
    if not project.created_at:
        project.created_at = now

    # Save to database
    execute_write(
        """INSERT OR REPLACE INTO projects (id, name, path, description, stack, repository, branch, environment, services, commands, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project.id,
            project.name,
            project.path,
            project.description,
            json.dumps(project.stack),
            project.repository,
            project.branch,
            project.environment,
            json.dumps(project.services),
            json.dumps(project.commands),
            json.dumps(project.notes),
            project.created_at,
            project.updated_at,
        ),
    )

    # Save to JSON file
    settings.projects_path.mkdir(parents=True, exist_ok=True)
    json_path = settings.projects_path / f"{project.id}.json"
    with open(json_path, "w") as f:
        json.dump(project.to_json(), f, indent=2)

    return project


def delete_project(project_id: str) -> bool:
    execute_write("DELETE FROM projects WHERE id = ?", (project_id,))
    json_path = settings.projects_path / f"{project_id}.json"
    json_path.unlink(missing_ok=True)
    return True


def create_default_projects() -> List[Project]:
    """Create example projects if none exist."""
    projects = load_all_projects()
    if projects:
        return projects

    defaults = [
        Project(
            id="mantis",
            name="Mantis",
            path="/var/www/mantis",
            description="Main production application",
            stack=["Next.js", "FastAPI", "PostgreSQL"],
            repository="https://github.com/example/mantis",
            branch="main",
            environment="production",
            services=["nginx", "postgresql", "mantis-api", "mantis-worker"],
            commands={"dev": "npm run dev", "test": "pytest", "build": "npm run build"},
            notes=["Production deployment at /var/www/mantis"],
        ),
        Project(
            id="apklab",
            name="APKLab",
            path="/var/www/apklab",
            description="APK analysis tool",
            stack=["Python", "FastAPI", "Redis"],
            repository="https://github.com/example/apklab",
            branch="main",
            environment="staging",
            services=["redis", "apklab-api"],
            commands={"dev": "uvicorn main:app --reload", "test": "pytest"},
            notes=[],
        ),
    ]

    for project in defaults:
        save_project(project)

    return defaults