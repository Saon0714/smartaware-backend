"""Staff: client notes, onboarding responses and wizard configuration."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import (
    CallerClientScope,
    CurrentUser,
    DbSession,
    require_permission,
)
from app.core.permissions import Permission
from app.models.client import Client
from app.models.note import Note
from app.models.onboarding import WizardQuestion, WizardStep
from app.models.user import User
from app.schemas.partial import make_partial
from app.schemas.profile import (
    NoteUpdate,
    NoteWrite,
    StaffNoteOut,
    WizardQuestionWrite,
    WizardStepOut,
    WizardStepWrite,
)

WizardStepPatch = make_partial(WizardStepWrite)
WizardQuestionPatch = make_partial(WizardQuestionWrite)

router = APIRouter(prefix="/admin", tags=["admin-notes"])

_can_view = Depends(require_permission(Permission.NOTE_VIEW))
_can_manage = Depends(require_permission(Permission.NOTE_MANAGE))
_content_editor = Depends(require_permission(Permission.CONTENT_MANAGE))


def _serialise(db: Session, note: Note) -> dict:
    client = db.get(Client, note.client_id)
    author = db.get(User, note.author_id) if note.author_id else None
    return {
        "id": note.id,
        "client_id": note.client_id,
        "client_ref": client.client_ref if client else "",
        "client_company_name": client.company_name if client else None,
        "title": note.title,
        "content": note.content,
        "is_visible_to_client": note.is_visible_to_client,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "author_name": (author.full_name or author.email) if author else None,
        "author_email": author.email if author else None,
    }


def _load(db: Session, scope, note_id: uuid.UUID) -> Note:
    note = db.get(Note, note_id)
    if note is None or not scope.allows(note.client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found.")
    return note


@router.get("/notes", response_model=list[StaffNoteOut], dependencies=[_can_view], name="list")
def list_notes(
    db: DbSession,
    scope: CallerClientScope,
    client_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Any:
    stmt = select(Note).order_by(Note.created_at.desc())
    stmt = scope.apply(stmt, Note.client_id)
    if client_id is not None:
        stmt = stmt.where(Note.client_id == client_id)
    return [_serialise(db, n) for n in db.execute(stmt).scalars()]


@router.post(
    "/notes",
    response_model=StaffNoteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_can_manage],
    name="create",
)
def create_note(
    payload: NoteWrite, user: CurrentUser, db: DbSession, scope: CallerClientScope
) -> Any:
    if not scope.allows(payload.client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")

    note = Note(
        client_id=payload.client_id,
        author_id=user.id,
        title=payload.title,
        content=payload.content,
        is_visible_to_client=payload.is_visible_to_client,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _serialise(db, note)


@router.patch(
    "/notes/{note_id}",
    response_model=StaffNoteOut,
    dependencies=[_can_manage],
    name="update",
)
def update_note(
    note_id: uuid.UUID, payload: NoteUpdate, db: DbSession, scope: CallerClientScope
) -> Any:
    note = _load(db, scope, note_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(note, field, value)
    db.commit()
    db.refresh(note)
    return _serialise(db, note)


@router.delete(
    "/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_can_manage],
    name="delete",
)
def delete_note(note_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> None:
    """A genuine delete.

    Unlike tasks and documents, a note is commentary rather than a record of
    work performed or a document a client relied on, so removing one destroys
    no evidence.
    """
    db.delete(_load(db, scope, note_id))
    db.commit()


# --- A client's onboarding answers -------------------------------------------------


@router.get(
    "/clients/{client_id}/onboarding",
    dependencies=[_can_view],
    name="client_onboarding",
)
def client_onboarding(client_id: uuid.UUID, db: DbSession, scope: CallerClientScope) -> Any:
    """What the client told us during onboarding, labelled rather than raw.

    Question keys mean nothing to a reader, and the wizard is editable, so the
    labels are resolved here instead of being duplicated in the frontend.
    """
    if not scope.allows(client_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.")

    from app.services import profile_service

    client = db.get(Client, client_id)
    answers = profile_service.read_answers(db, client_id)
    steps = profile_service.wizard_steps(db)

    return {
        "completed_at": client.onboarding_completed_at if client else None,
        "steps": [
            {
                "title": step.title,
                "answers": [
                    {
                        "label": question.label,
                        "value": answers.get(question.key),
                    }
                    for question in sorted(
                        (q for q in step.questions if q.is_active),
                        key=lambda q: q.sort_order,
                    )
                ],
            }
            for step in steps
        ],
    }


# --- Wizard configuration (Section 13 item 2) ----------------------------------------

wizard = APIRouter(prefix="/wizard", tags=["admin-wizard"], dependencies=[_content_editor])


@wizard.get("/steps", response_model=list[WizardStepOut], name="list_steps")
def list_steps(db: DbSession) -> Any:
    steps = db.execute(
        select(WizardStep)
        .options(selectinload(WizardStep.questions))
        .order_by(WizardStep.sort_order)
    ).scalars()
    return [
        {
            "id": s.id,
            "key": s.key,
            "title": s.title,
            "description": s.description,
            "sort_order": s.sort_order,
            "questions": sorted(s.questions, key=lambda q: q.sort_order),
        }
        for s in steps
    ]


@wizard.post("/steps", response_model=WizardStepOut, status_code=201, name="create_step")
def create_step(payload: WizardStepWrite, db: DbSession) -> Any:
    if db.execute(select(WizardStep).where(WizardStep.key == payload.key)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A step with that key exists."
        )
    step = WizardStep(**payload.model_dump())
    db.add(step)
    db.commit()
    db.refresh(step)
    return {**payload.model_dump(), "id": step.id, "questions": []}


@wizard.patch("/steps/{step_id}", response_model=WizardStepOut, name="update_step")
def update_step(step_id: uuid.UUID, payload: WizardStepPatch, db: DbSession) -> Any:
    step = db.get(WizardStep, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(step, field, value)
    db.commit()
    db.refresh(step)
    return {
        "id": step.id,
        "key": step.key,
        "title": step.title,
        "description": step.description,
        "sort_order": step.sort_order,
        "questions": sorted(step.questions, key=lambda q: q.sort_order),
    }


@wizard.delete("/steps/{step_id}", status_code=204, name="deactivate_step")
def deactivate_step(step_id: uuid.UUID, db: DbSession) -> None:
    """Deactivated rather than deleted.

    Clients' answers reference this step's questions; removing the rows would
    orphan them and lose what those clients told us.
    """
    step = db.get(WizardStep, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    step.is_active = False
    db.commit()


@wizard.post(
    "/steps/{step_id}/questions",
    response_model=WizardStepOut,
    status_code=201,
    name="create_question",
)
def create_question(step_id: uuid.UUID, payload: WizardQuestionWrite, db: DbSession) -> Any:
    step = db.get(WizardStep, step_id)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if any(q.key == payload.key for q in step.questions):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A question with that key already exists on this step.",
        )
    db.add(WizardQuestion(step_id=step_id, **payload.model_dump()))
    db.commit()
    db.refresh(step)
    return {
        "id": step.id,
        "key": step.key,
        "title": step.title,
        "description": step.description,
        "sort_order": step.sort_order,
        "questions": sorted(step.questions, key=lambda q: q.sort_order),
    }


@wizard.delete("/questions/{question_id}", status_code=204, name="deactivate_question")
def deactivate_question(question_id: uuid.UUID, db: DbSession) -> None:
    question = db.get(WizardQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    question.is_active = False
    db.commit()


router.include_router(wizard)
