from fastapi import APIRouter
from app.config import settings
from app.storage.database import get_connection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    db_ok = False
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "version": "1.0.0",
    }


@router.get("/health/ready")
async def readiness_check():
    """Readiness check for Kubernetes/load balancers."""
    return await health_check()