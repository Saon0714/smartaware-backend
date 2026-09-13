"""Root API router.

Every versioned router is mounted here so `main.py` stays a thin app factory
and the full API surface is discoverable from one file.
"""

from fastapi import APIRouter

from app.api.v1 import health
from app.api.v1.admin import clients as admin_clients
from app.api.v1.admin import content as admin_content
from app.api.v1.admin import enquiries as admin_enquiries
from app.api.v1.admin import faq as admin_faq
from app.api.v1.admin import invites as admin_invites
from app.api.v1.admin import services as admin_services
from app.api.v1.auth import routes as auth_routes
from app.api.v1.public import chat as public_chat
from app.api.v1.public import content as public_content
from app.api.v1.public import enquiries as public_enquiries
from app.api.v1.public import services as public_services

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth_routes.router)
api_router.include_router(public_content.router)
api_router.include_router(public_services.router)
api_router.include_router(public_enquiries.router)
api_router.include_router(public_chat.router)
api_router.include_router(admin_invites.router)
api_router.include_router(admin_content.router)
api_router.include_router(admin_services.router)
api_router.include_router(admin_enquiries.router)
api_router.include_router(admin_faq.router)
api_router.include_router(admin_clients.router)
