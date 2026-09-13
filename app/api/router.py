"""Root API router.

Every versioned router is mounted here so `main.py` stays a thin app factory
and the full API surface is discoverable from one file.
"""

from fastapi import APIRouter

from app.api.v1 import health
from app.api.v1.admin import content as admin_content
from app.api.v1.admin import invites as admin_invites
from app.api.v1.auth import routes as auth_routes
from app.api.v1.public import content as public_content

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth_routes.router)
api_router.include_router(public_content.router)
api_router.include_router(admin_invites.router)
api_router.include_router(admin_content.router)
