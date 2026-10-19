from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.skills import (
    list_skills,
    get_skill,
    write_skill,
    delete_skill,
    InvalidSkillNameError,
    SkillNotFoundError,
)

router = APIRouter(prefix="/skills", tags=["skills"], dependencies=[Depends(get_current_user)])


class SkillWrite(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    body: str = ""


@router.get("")
async def list_skills_endpoint():
    """List configured skills - name + description only. Same data the
    agent's system prompt is seeded with (see app/agent/context.py)."""
    return {"skills": [{"name": s.name, "description": s.description} for s in list_skills()]}


@router.get("/{name}")
async def get_skill_endpoint(name: str):
    """Full skill content: description, instruction body, and any other
    files present in that skill's directory."""
    try:
        skill = get_skill(name)
    except InvalidSkillNameError as e:
        raise HTTPException(400, str(e))
    except SkillNotFoundError as e:
        raise HTTPException(404, str(e))
    return {
        "name": skill.name,
        "description": skill.description,
        "body": skill.body,
        "files": skill.files,
    }


@router.put("/{name}")
async def put_skill_endpoint(name: str, request: SkillWrite):
    """Create a new skill, or overwrite an existing one's SKILL.md (only
    SKILL.md - other files already in that skill's directory are left
    alone). Takes effect on the next message: the system prompt is
    rebuilt fresh at the start of every AgentExecutor.run(), same as
    mode/model/reasoning_effort."""
    try:
        skill = write_skill(name, request.description, request.body)
    except InvalidSkillNameError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "status": "saved",
        "name": skill.name,
        "description": skill.description,
        "body": skill.body,
        "files": skill.files,
    }


@router.delete("/{name}")
async def delete_skill_endpoint(name: str):
    """Remove a skill entirely, including any supporting files in its directory."""
    try:
        delete_skill(name)
    except InvalidSkillNameError as e:
        raise HTTPException(400, str(e))
    except SkillNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"status": "deleted"}
