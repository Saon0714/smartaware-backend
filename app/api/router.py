"""Root API router.

Every versioned router is mounted here so `main.py` stays a thin app factory
and the full API surface is discoverable from one file.
"""

from fastapi import APIRouter, Depends

from app.api.v1 import health
from app.api.v1.admin import clients as admin_clients
from app.api.v1.admin import content as admin_content
from app.api.v1.admin import documents as admin_documents
from app.api.v1.admin import enquiries as admin_enquiries
from app.api.v1.admin import faq as admin_faq
from app.api.v1.admin import invites as admin_invites
from app.api.v1.admin import services as admin_services
from app.api.v1.admin import settings as admin_settings
from app.api.v1.admin import tasks as admin_tasks
from app.api.v1.auth import routes as auth_routes
from app.api.v1.portal import documents as portal_documents
from app.api.v1.portal import tasks as portal_tasks
from app.api.v1.public import chat as public_chat
from app.api.v1.public import content as public_content
from app.api.v1.public import enquiries as public_enquiries
from app.api.v1.public import services as public_services
from app.core.deps import require_role
from app.models.enums import UserRole

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth_routes.router)

# --- Public -------------------------------------------------------------------

api_router.include_router(public_content.router)
api_router.include_router(public_services.router)
api_router.include_router(public_enquiries.router)
api_router.include_router(public_chat.router)

# --- Client portal ------------------------------------------------------------

api_router.include_router(portal_tasks.router)
api_router.include_router(portal_documents.router)

# --- Staff -------------------------------------------------------------------
#
# Everything under /admin requires a staff role, on top of whatever permission
# the individual endpoint declares. Several permissions are deliberately shared
# between a client and staff — a client may view their own tasks, documents,
# invoices and notes — so a permission check alone would let a client call the
# staff endpoint and receive the staff serialisation, which carries internal
# fields the portal view withholds. Clients have their own /portal routes.

staff_router = APIRouter(dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.MANAGER))])
staff_router.include_router(admin_invites.router)
staff_router.include_router(admin_content.router)
staff_router.include_router(admin_services.router)
staff_router.include_router(admin_enquiries.router)
staff_router.include_router(admin_faq.router)
staff_router.include_router(admin_clients.router)
staff_router.include_router(admin_tasks.router)
staff_router.include_router(admin_settings.router)
staff_router.include_router(admin_documents.router)

api_router.include_router(staff_router)
