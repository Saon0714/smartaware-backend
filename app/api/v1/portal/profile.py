"""Client portal: profile, onboarding and notes.

Spec Sections 5.2, 5.3.A and 5.3.G. Every query resolves the client from the
caller's own scope, so there is no identifier in any of these requests that
could point at somebody else's record.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CallerClientScope, DbSession
from app.models.client import Client
from app.models.note import Note
from app.models.user import User
from app.schemas.profile import (
    AssignedManagerOut,
    NoteOut,
    OnboardingAnswers,
    OnboardingOut,
    ProfileOut,
    ProfileUpdate,
)
from app.services import profile_service

router = APIRouter(prefix="/portal", tags=["portal-profile"])


def _own_client(db: Session, scope) -> Client:
    """The caller's own client record.

    Taken from their scope rather than a request parameter, which is what makes
    these endpoints impossible to point at another account.
    """
    if len(scope.client_ids) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This section is only available to client accounts.",
        )
    client = db.get(Client, next(iter(scope.client_ids)))
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return client


@router.get("/profile", response_model=ProfileOut, summary="My profile")
def my_profile(db: DbSession, scope: CallerClientScope) -> Any:
    client = _own_client(db, scope)
    form = profile_service.get_form(db)
    if form is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The profile form is unavailable.",
        )
    manager = (
        db.get(User, client.assigned_manager_id) if client.assigned_manager_id else None
    )
    return ProfileOut(
        fields=profile_service.active_fields(form),
        values=profile_service.read_values(client, form),
        client_ref=client.client_ref,
        status=client.status.value,
        onboarding_completed_at=client.onboarding_completed_at,
        assigned_manager=(
            # Only while the manager is active: pointing a client at someone who
            # has left is worse than showing nobody.
            AssignedManagerOut(full_name=manager.full_name, email=manager.email)
            if manager and manager.is_active
            else None
        ),
    )


@router.patch("/profile", response_model=ProfileOut, summary="Update my profile")
def update_my_profile(payload: ProfileUpdate, db: DbSession, scope: CallerClientScope) -> Any:
    client = _own_client(db, scope)
    form = profile_service.get_form(db)
    if form is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The profile form is unavailable.",
        )

    try:
        profile_service.update_values(db, client, form, payload.values)
    except profile_service.ProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    db.commit()
    db.refresh(client)
    return my_profile(db, scope)


# --- Onboarding (Section 5.2) ----------------------------------------------------


@router.get("/onboarding", response_model=OnboardingOut, summary="The onboarding wizard")
def my_onboarding(db: DbSession, scope: CallerClientScope) -> Any:
    client = _own_client(db, scope)
    steps = profile_service.wizard_steps(db)
    return OnboardingOut(
        steps=[
            {
                "id": step.id,
                "key": step.key,
                "title": step.title,
                "description": step.description,
                "sort_order": step.sort_order,
                "questions": sorted(
                    (q for q in step.questions if q.is_active),
                    key=lambda q: q.sort_order,
                ),
            }
            for step in steps
        ],
        answers=profile_service.read_answers(db, client.id),
        completed_at=client.onboarding_completed_at,
    )


@router.post("/onboarding", response_model=OnboardingOut, summary="Save onboarding answers")
def save_my_onboarding(payload: OnboardingAnswers, db: DbSession, scope: CallerClientScope) -> Any:
    """Saves progress, and marks the wizard complete only when asked.

    Required answers are checked at completion rather than on every save, so a
    long wizard can be left half-finished and resumed.
    """
    client = _own_client(db, scope)
    try:
        profile_service.save_answers(
            db, client=client, submitted=payload.answers, complete=payload.complete
        )
    except profile_service.ProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    db.commit()
    return my_onboarding(db, scope)


# --- Notes (Section 5.3.G) --------------------------------------------------------


@router.get("/notes", response_model=list[NoteOut], summary="Notes from SmartAWARE")
def my_notes(db: DbSession, scope: CallerClientScope) -> Any:
    """Read-only.

    There is no write route here at all: Section 5.3.G describes notes as
    information shared by SmartAWARE, so a client can read them and nothing
    more. Drafts are excluded — staff can prepare a note before it is visible.
    """
    stmt = select(Note).where(Note.is_visible_to_client.is_(True)).order_by(Note.created_at.desc())
    stmt = scope.apply(stmt, Note.client_id)

    notes = list(db.execute(stmt).scalars())
    authors = {
        u.id: u
        for u in db.execute(
            select(User).where(User.id.in_([n.author_id for n in notes if n.author_id]))
        ).scalars()
    }
    return [
        {
            "id": note.id,
            "client_id": note.client_id,
            "title": note.title,
            "content": note.content,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
            # A name, not an account — who wrote it is useful, their user
            # record is not the client's business.
            "author_name": (
                (authors[note.author_id].full_name or authors[note.author_id].email)
                if note.author_id in authors
                else None
            ),
        }
        for note in notes
    ]
