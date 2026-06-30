"""
Hermes — JARVIS OS AI Brain
FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from src.config import settings
from src.db.connection import init_db, close_db
from src.core.scheduler import scheduler, register_core_jobs
from src.api.routes import health, briefings, memory, tasks, notifications, voice, scheduler as scheduler_routes, intelligence, coolify as coolify_routes, rdp as rdp_routes, meta_ads as meta_ads_routes

# Configure structured logging
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level)
    ),
)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log.info("hermes.starting", env=settings.env)

    # Initialize database
    await init_db()
    log.info("hermes.db.ready")

    # Register and start scheduler
    register_core_jobs()
    scheduler.start()
    log.info("hermes.scheduler.started")

    log.info("hermes.ready", port=settings.port)
    yield

    # Shutdown
    log.info("hermes.shutting_down")
    scheduler.shutdown(wait=False)
    await close_db()
    log.info("hermes.stopped")


app = FastAPI(
    title="Hermes",
    description="JARVIS OS AI Brain — memory, scheduling, planning, notifications",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
)

# CORS — internal only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3002",
        "http://localhost:8001",
        "http://dashboard:3000",
        "http://jarvis-dashboard:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Routes
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(briefings.router, prefix="/api/v1/briefings", tags=["briefings"])
app.include_router(memory.router, prefix="/api/v1/memory", tags=["memory"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(voice.router, prefix="/api/v1/voice", tags=["voice"])
app.include_router(scheduler_routes.router, prefix="/api/v1/scheduler", tags=["scheduler"])
app.include_router(intelligence.router, prefix="/api/v1/intelligence", tags=["intelligence"])
app.include_router(coolify_routes.router)
app.include_router(rdp_routes.router)
app.include_router(meta_ads_routes.router)
