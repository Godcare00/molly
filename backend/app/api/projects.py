from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from pydantic import BaseModel

from app.storage.projects import (
    load_project,
    load_all_projects,
    save_project,
    delete_project,
    create_default_projects,
    Project,
)
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(get_current_user)])


class ProjectCreate(BaseModel):
    id: str
    name: str
    path: str
    description: str = ""
    stack: list[str] = []
    repository: str = ""
    branch: str = "main"
    environment: str = "development"
    services: list[str] = []
    commands: dict = {}
    notes: list[str] = []


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    description: Optional[str] = None
    stack: Optional[list[str]] = None
    repository: Optional[str] = None
    branch: Optional[str] = None
    environment: Optional[str] = None
    services: Optional[list[str]] = None
    commands: Optional[dict] = None
    notes: Optional[list[str]] = None


@router.get("")
async def list_projects():
    """List all registered projects."""
    projects = load_all_projects()
    return [
        {
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
        for p in projects
    ]


@router.get("/{project_id}")
async def get_project(project_id: str):
    """Get project details."""
    project = load_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    return {
        "id": project.id,
        "name": project.name,
        "path": project.path,
        "description": project.description,
        "stack": project.stack,
        "repository": project.repository,
        "branch": project.branch,
        "environment": project.environment,
        "services": project.services,
        "commands": project.commands,
        "notes": project.notes,
    }


@router.post("")
async def create_project(request: ProjectCreate):
    """Create or update a project."""
    project = Project(
        id=request.id,
        name=request.name,
        path=request.path,
        description=request.description,
        stack=request.stack,
        repository=request.repository,
        branch=request.branch,
        environment=request.environment,
        services=request.services,
        commands=request.commands,
        notes=request.notes,
    )

    save_project(project)
    return {"status": "created", "project_id": project.id}


@router.put("/{project_id}")
async def update_project(project_id: str, request: ProjectUpdate):
    """Update a project."""
    project = load_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    if request.name is not None:
        project.name = request.name
    if request.path is not None:
        project.path = request.path
    if request.description is not None:
        project.description = request.description
    if request.stack is not None:
        project.stack = request.stack
    if request.repository is not None:
        project.repository = request.repository
    if request.branch is not None:
        project.branch = request.branch
    if request.environment is not None:
        project.environment = request.environment
    if request.services is not None:
        project.services = request.services
    if request.commands is not None:
        project.commands = request.commands
    if request.notes is not None:
        project.notes = request.notes

    save_project(project)
    return {"status": "updated", "project_id": project.id}


@router.delete("/{project_id}")
async def delete_project_endpoint(project_id: str):
    """Delete a project."""
    project = load_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    delete_project(project_id)
    return {"status": "deleted"}