"""Root API router.

Every versioned router is mounted here so `main.py` stays a thin app factory
and the full API surface is discoverable from one file.
"""

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router)
