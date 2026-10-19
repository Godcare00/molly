from app.api.health import router as health_router
from app.api.routes import router as conversations_router
from app.api.approvals import router as approvals_router
from app.api.questionnaires import router as questionnaires_router
from app.api.images import router as images_router
from app.api.files import router as files_router
from app.api.projects import router as projects_router
from app.api.settings import router as settings_router
from app.api.skills import router as skills_router
from app.api.websocket import manager

__all__ = [
    "health_router",
    "conversations_router",
    "approvals_router",
    "questionnaires_router",
    "images_router",
    "files_router",
    "projects_router",
    "settings_router",
    "skills_router",
    "manager",
]