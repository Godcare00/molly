from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
import asyncio
import uvicorn
import time
import structlog

from app.config import settings
from app.storage.database import init_db, close_db
from app.storage.projects import create_default_projects
from app.tools import registry
from app.api import (
    health_router,
    conversations_router,
    approvals_router,
    questionnaires_router,
    images_router,
    files_router,
    projects_router,
    settings_router,
    skills_router,
)
from app.llm.client import close_provider


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer() if not settings.debug else structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


# Prometheus metrics (lazy initialization to avoid double registration on reload)
_metrics_initialized = False
METRICS_ENABLED = False

http_requests_total = None
http_request_duration_seconds = None
agent_runs_total = None
agent_iterations = None
agent_tool_calls_total = None
agent_tool_duration_seconds = None
approvals_total = None
approval_duration_seconds = None
llm_requests_total = None
llm_tokens_total = None
llm_request_duration_seconds = None
llm_provider_fallback_total = None
ws_connections_active = None
ws_messages_total = None

def init_metrics():
    """Initialize Prometheus metrics (call once at startup)."""
    global _metrics_initialized, METRICS_ENABLED
    global http_requests_total, http_request_duration_seconds
    global agent_runs_total, agent_iterations, agent_tool_calls_total, agent_tool_duration_seconds
    global approvals_total, approval_duration_seconds
    global llm_requests_total, llm_tokens_total, llm_request_duration_seconds
    global llm_provider_fallback_total
    global ws_connections_active, ws_messages_total
    
    if _metrics_initialized:
        return
    
    try:
        from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
        global generate_latest, CONTENT_TYPE_LATEST
    except ImportError:
        METRICS_ENABLED = False
        return
    
    # Request metrics
    http_requests_total = Counter(
        'molly_http_requests_total',
        'Total HTTP requests',
        ['method', 'endpoint', 'status']
    )
    http_request_duration_seconds = Histogram(
        'molly_http_request_duration_seconds',
        'HTTP request duration in seconds',
        ['method', 'endpoint']
    )
    
    # Agent metrics
    agent_runs_total = Counter(
        'molly_agent_runs_total',
        'Total agent runs',
        ['status']
    )
    agent_iterations = Histogram(
        'molly_agent_iterations',
        'Number of iterations per agent run'
    )
    agent_tool_calls_total = Counter(
        'molly_agent_tool_calls_total',
        'Total tool calls',
        ['tool', 'status']
    )
    agent_tool_duration_seconds = Histogram(
        'molly_agent_tool_duration_seconds',
        'Tool execution duration in seconds',
        ['tool']
    )
    
    # Approval metrics
    approvals_total = Counter(
        'molly_approvals_total',
        'Total approval requests',
        ['tool', 'risk_level', 'outcome']
    )
    approval_duration_seconds = Histogram(
        'molly_approval_duration_seconds',
        'Time from approval request to resolution',
        ['outcome']
    )
    
    # LLM metrics
    llm_requests_total = Counter(
        'molly_llm_requests_total',
        'Total LLM requests',
        ['model', 'status']
    )
    llm_tokens_total = Counter(
        'molly_llm_tokens_total',
        'Total tokens used',
        ['model', 'type']
    )
    llm_request_duration_seconds = Histogram(
        'molly_llm_request_duration_seconds',
        'LLM request duration in seconds',
        ['model']
    )
    llm_provider_fallback_total = Counter(
        'molly_llm_provider_fallback_total',
        'Times a provider failed (after retries) and the chain moved to the next one',
        ['from_provider', 'to_provider']
    )
    
    # WebSocket metrics
    ws_connections_active = Gauge(
        'molly_ws_connections_active',
        'Active WebSocket connections'
    )
    ws_messages_total = Counter(
        'molly_ws_messages_total',
        'Total WebSocket messages',
        ['direction', 'type']
    )
    
    METRICS_ENABLED = True
    _metrics_initialized = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_metrics()
    init_db()
    create_default_projects()
    logger.info("molly_backend_started", host=settings.host, port=settings.port)
    logger.info("registered_tools", tools=registry.list_tools())

    # Fleet gateway tunnel - this worker is only reachable through it now
    # (see app/auth/dependencies.py's relay-token-only get_current_user).
    # A worker with no saved credential (never enrolled) or no
    # gateway_ws_url configured simply won't accept any authenticated
    # request until `molly worker enroll` is run.
    tunnel_task = None
    from app.tunnel.enrollment import load_credential
    cred = load_credential()
    gateway_ws_url = settings.gateway_ws_url or (cred or {}).get("gateway_ws_url", "")
    if gateway_ws_url and cred:
        from app.tunnel.client import TunnelClient
        tunnel_client = TunnelClient(
            gateway_ws_url=gateway_ws_url,
            worker_id=cred["worker_id"],
            worker_token=cred["worker_token"],
            worker_secret=cred["worker_secret"],
            asgi_app=app,
        )
        app.state.tunnel_client = tunnel_client
        tunnel_task = asyncio.ensure_future(tunnel_client.run_forever())
        logger.info("fleet_tunnel_starting", worker_id=cred["worker_id"], gateway_ws_url=gateway_ws_url)
    elif gateway_ws_url and not cred:
        logger.warning(
            "gateway_configured_but_not_enrolled",
            hint="run `python -m app.cli worker enroll --gateway <http-url> --token <token>` first",
        )

    yield

    # Shutdown
    if tunnel_task:
        app.state.tunnel_client.stop()
        tunnel_task.cancel()
    await close_provider()
    close_db()
    logger.info("molly_backend_stopped")


app = FastAPI(
    title="Molly Backend",
    description="Autonomous DevOps Assistant API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_hosts_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    # Log request
    logger.info(
        "http_request_started",
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else None,
    )
    
    response = await call_next(request)
    
    duration = time.time() - start_time
    
    # Log response
    logger.info(
        "http_request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )
    
    # Record metrics
    if METRICS_ENABLED:
        http_requests_total.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)
    
    return response


# Include routers
app.include_router(health_router)
app.include_router(conversations_router)
app.include_router(approvals_router)
app.include_router(questionnaires_router)
app.include_router(images_router)
app.include_router(files_router)
app.include_router(projects_router)
app.include_router(settings_router)
app.include_router(skills_router)


@app.get("/")
async def root():
    return {
        "name": "Molly Backend",
        "version": "1.0.0",
        "description": "Autonomous DevOps Assistant API",
        "tools": registry.list_tools(),
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    if not METRICS_ENABLED:
        return Response(content="Metrics not available (prometheus_client not installed)", status_code=503)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    if settings.debug:
        # Reload spawns a subprocess that re-imports "app.main" by name, so
        # it needs the string form and the actual .py source on disk. Dev
        # only - not used by the compiled binary, which never runs debug.
        uvicorn.run(
            "app.main:app",
            host=settings.host,
            port=settings.port,
            reload=True,
        )
    else:
        # Pass the already-constructed app object directly. This is what
        # both `python -m app.main` and the Nuitka-compiled binary use in
        # production, and it avoids re-importing this module under a
        # different name (which would build a second, unused FastAPI app).
        uvicorn.run(app, host=settings.host, port=settings.port)