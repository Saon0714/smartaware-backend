"""Liveness and readiness endpoints.

`/health` must stay dependency-free so a load balancer can distinguish
"process is up" from "process can reach its dependencies" (`/health/ready`,
added in Chunk 1 once the DB session exists).
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.db import schema_version

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str
    #: "ok", "stale" or "unknown". A database left behind a migration answers
    #: every page that touches a changed table with a 500 and no explanation,
    #: so it is worth being able to ask.
    schema_status: str = "unknown"
    schema_expected: str | None = None
    schema_applied: str | None = None


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    version = schema_version.read()
    return HealthResponse(
        status="ok",
        environment=settings.ENVIRONMENT,
        version="0.1.0",
        schema_status=version.status,
        schema_expected=version.expected,
        schema_applied=version.applied,
    )
