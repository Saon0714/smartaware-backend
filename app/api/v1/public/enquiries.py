"""Public enquiry form — spec Section 3.2."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.core import rate_limit
from app.core.config import settings
from app.core.deps import DbSession
from app.schemas.enquiry import EnquiryAccepted, EnquiryCreate, FormDefinitionOut
from app.services import enquiry_service
from app.services.notification import NotificationEvent, dispatch, prepare

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public-enquiries"])

RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 3600


@router.get(
    "/forms/{form_key}",
    response_model=FormDefinitionOut,
    summary="A form's field definition",
)
def get_form(form_key: str, db: DbSession) -> FormDefinitionOut:
    """The frontend renders whatever this returns.

    Adding, removing or relabelling a field is therefore an Admin Portal edit,
    with no frontend change and no deploy.
    """
    form = enquiry_service.get_form(db, form_key)
    if form is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found.")
    return FormDefinitionOut.model_validate(enquiry_service.describe_form(db, form))


@router.post(
    "/enquiries",
    response_model=EnquiryAccepted,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an enquiry",
)
def submit_enquiry(
    payload: EnquiryCreate,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
) -> EnquiryAccepted:
    form = enquiry_service.get_form(db)
    if form is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The enquiry form is not available at the moment.",
        )

    # A filled honeypot means a bot. Answer as though it succeeded rather than
    # returning an error that would tell the author how to get past it.
    if payload.website:
        logger.info("Discarded a honeypot enquiry submission.")
        return EnquiryAccepted(id=form.id, message="Thank you. We will be in touch shortly.")

    ip = rate_limit.client_ip(request)
    if not rate_limit.check(f"enquiry:{ip}", limit=RATE_LIMIT, window_seconds=RATE_WINDOW_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many enquiries from this connection. Please try again later.",
        )

    try:
        enquiry = enquiry_service.create_enquiry(db, form, payload.answers)
    except enquiry_service.EnquiryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Recipients and wording are resolved here, while the session and the data
    # are to hand. Only the sending is deferred, so the submitter never waits on
    # an email and a mail failure cannot affect a submission already stored.
    message = prepare(
        db,
        NotificationEvent.ENQUIRY_SUBMITTED,
        {
            "name": enquiry.name or "a website visitor",
            "summary": enquiry_service.summarise(form, enquiry),
            "admin_url": f"{settings.FRONTEND_BASE_URL.rstrip('/')}/admin/enquiries",
        },
    )
    db.commit()
    background.add_task(dispatch, message)

    return EnquiryAccepted(id=enquiry.id, message="Thank you. We will be in touch shortly.")
