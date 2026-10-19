from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI

from app.api import account, admin_devices, admin_workers, health, mobile_ws, pairing, proxy, worker_ws
from app.config import settings
from app.db import init_models
from app.tunnel.bus import close_bus, init_bus

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer() if not settings.debug else structlog.dev.ConsoleRenderer(),
    ],
)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    await init_bus()
    logger.info(
        "gateway_started",
        host=settings.host,
        port=settings.port,
        database_url=settings.database_url,
        redis_url=settings.redis_url or "(single-process mode)",
    )
    yield
    await close_bus()
    logger.info("gateway_stopped")


app = FastAPI(
    title="Molly Gateway",
    description="Multi-tenant auth/routing/connections front-end for a fleet of Molly server workers",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(worker_ws.router)     # /worker/connect - workers dial in here
app.include_router(mobile_ws.router)     # /w/{worker_id}/ws/conversations/{id} - mobile realtime traffic
app.include_router(account.router)        # /auth/signup, /auth/login - real email/password accounts
app.include_router(admin_workers.router)  # /admin/workers/* - fleet management + enrollment
app.include_router(admin_devices.router)  # /auth/refresh, /auth/me, /auth/logout, /admin/devices/{id}/revoke
app.include_router(pairing.router)        # /worker/pairing-codes, /devices/pair
app.include_router(proxy.router)         # /w/{worker_id}/{path:path} - catch-all REST proxy, registered last


@app.get("/")
async def root():
    return {"name": "Molly Gateway", "version": "0.1.0"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
