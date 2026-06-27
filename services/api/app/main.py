from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.database import init_db
from app.middleware.error_handler import add_error_handlers
from app.middleware.logging import RequestLoggingMiddleware, setup_logging
from app.redis_client import init_redis
from app.routers import audit_logs, auth, config_mgmt, health, servers, users, chat, admin_llm, incidents

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    settings._validate_secrets()
    await init_db()
    init_redis()
    log.info("startup_complete", env=settings.app_env, log_level=settings.log_level)
    yield
    log.info("shutdown")


app = FastAPI(
    title="VST AI OpsAI Platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS phải đứng trước các middleware khác
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
add_error_handlers(app)

# Prometheus metrics — exclude health/ready/metrics endpoints
Instrumentator(
    excluded_handlers=["/health", "/ready", "/metrics"]
).instrument(app).expose(app)

# Routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(servers.router)
app.include_router(config_mgmt.router)
app.include_router(audit_logs.router)
app.include_router(chat.router)
app.include_router(admin_llm.router)
app.include_router(incidents.router)
