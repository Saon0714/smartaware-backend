"""Liveness and readiness endpoints.

`/health` must stay dependency-free so a load balancer can distinguish
"process is up" from "process can reach its dependencies" (`/health/ready`,
added in Chunk 1 once the DB session exists).
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.ENVIRONMENT, version="0.1.0")
