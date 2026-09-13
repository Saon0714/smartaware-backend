"""Admin: FAQ content and chat transcripts.

Spec Section 4.3 makes FAQ management a hard constraint — no code change may be
required to update FAQ content — so entries are full CRUD here and the nightly
job picks up whatever changed.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require_permission
from app.core.permissions import Permission
from app.core.settings_service import SettingKey, get_setting
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import UserRole
from app.models.faq import FaqEmbedding, FaqEntry
from app.schemas.chat import (
    ChatSessionDetail,
    ChatSessionOut,
    FaqEntryOut,
    FaqEntryWrite,
    FaqIndexStatus,
)
from app.schemas.partial import make_partial

FaqEntryPatch = make_partial(FaqEntryWrite)

router = APIRouter(prefix="/admin", tags=["admin-faq"])

_faq_editor = Depends(require_permission(Permission.FAQ_MANAGE))


@router.get("/faq", response_model=list[FaqEntryOut], dependencies=[_faq_editor], name="list")
def list_faq(
    db: DbSession,
    include_deleted: Annotated[bool, Query()] = False,
) -> Any:
    stmt = select(FaqEntry).order_by(FaqEntry.sort_order, FaqEntry.question)
    if not include_deleted:
        stmt = stmt.where(FaqEntry.is_deleted.is_(False))
    return list(db.execute(stmt).scalars())


@router.post(
    "/faq",
    response_model=FaqEntryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_faq_editor],
    name="create",
)
def create_faq(payload: FaqEntryWrite, db: DbSession) -> Any:
    entry = FaqEntry(**payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.patch(
    "/faq/{entry_id}",
    response_model=FaqEntryOut,
    dependencies=[_faq_editor],
    name="update",
)
def update_faq(entry_id: uuid.UUID, payload: FaqEntryPatch, db: DbSession) -> Any:
    entry = db.get(FaqEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    # `updated_at` moves ahead of `indexed_at`, which is exactly what marks the
    # entry stale for the next incremental run.
    db.commit()
    db.refresh(entry)
    return entry


@router.delete(
    "/faq/{entry_id}",
    response_model=FaqEntryOut,
    dependencies=[_faq_editor],
    name="delete",
)
def delete_faq(entry_id: uuid.UUID, db: DbSession) -> Any:
    """Soft delete.

    Section 4.4 relies on it: a hard delete would leave the entry's embeddings
    orphaned in the vector table with nothing left to tell the indexer they
    should go.
    """
    from datetime import UTC, datetime

    entry = db.get(FaqEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    entry.is_deleted = True
    entry.deleted_at = datetime.now(UTC)
    entry.is_published = False
    db.commit()
    db.refresh(entry)
    return entry


@router.post(
    "/faq/{entry_id}/restore",
    response_model=FaqEntryOut,
    dependencies=[_faq_editor],
    name="restore",
)
def restore_faq(entry_id: uuid.UUID, db: DbSession) -> Any:
    entry = db.get(FaqEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    entry.is_deleted = False
    entry.deleted_at = None
    # Force a re-embed: the entry's vectors were removed while it was deleted.
    entry.indexed_at = None
    db.commit()
    db.refresh(entry)
    return entry


@router.get(
    "/faq-index/status",
    response_model=FaqIndexStatus,
    dependencies=[_faq_editor],
    name="index_status",
)
def index_status(db: DbSession) -> FaqIndexStatus:
    """What the nightly job would do if it ran now."""
    total = db.execute(
        select(func.count()).select_from(FaqEntry).where(FaqEntry.is_deleted.is_(False))
    ).scalar_one()

    pending = db.execute(
        select(func.count())
        .select_from(FaqEntry)
        .where(
            FaqEntry.is_deleted.is_(False),
            FaqEntry.is_published.is_(True),
            or_(
                FaqEntry.indexed_at.is_(None),
                FaqEntry.updated_at > FaqEntry.indexed_at,
            ),
        )
    ).scalar_one()

    retired = db.execute(
        select(func.count(func.distinct(FaqEntry.id)))
        .select_from(FaqEntry)
        .join(FaqEmbedding, FaqEmbedding.faq_id == FaqEntry.id)
        .where(or_(FaqEntry.is_deleted.is_(True), FaqEntry.is_published.is_(False)))
    ).scalar_one()

    last = db.execute(select(func.max(FaqEntry.indexed_at))).scalar_one()

    return FaqIndexStatus(
        total=total,
        indexed=total - pending,
        pending=pending,
        retired=retired,
        last_indexed_at=last,
    )


# --- Chat transcripts (Section 13 item 8) ---------------------------------------


def _assert_may_read_logs(db, user) -> None:
    """Visibility is a setting, defaulted to Admin only."""
    allowed = get_setting(db, SettingKey.CHAT_LOGS_VISIBLE_TO, "admin")
    if allowed == "nobody":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat transcript access is disabled.",
        )
    if allowed == "admin" and user.role is not UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an administrator may read chat transcripts.",
        )
    if allowed == "admin_and_manager" and user.role not in (
        UserRole.ADMIN,
        UserRole.MANAGER,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to read chat transcripts.",
        )


@router.get("/chat-sessions", response_model=list[ChatSessionOut], name="list_sessions")
def list_sessions(
    user: CurrentUser,
    db: DbSession,
    escalated_only: Annotated[bool, Query()] = False,
) -> Any:
    _assert_may_read_logs(db, user)

    counts = (
        select(ChatMessage.session_id, func.count().label("n"))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    stmt = (
        select(ChatSession, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.session_id == ChatSession.id)
        .order_by(ChatSession.created_at.desc())
    )
    if escalated_only:
        escalations = select(ChatMessage.session_id).where(ChatMessage.escalated.is_(True))
        stmt = stmt.where(ChatSession.id.in_(escalations))

    return [
        ChatSessionOut.model_validate(session).model_copy(update={"message_count": count})
        for session, count in db.execute(stmt).all()
    ]


@router.get(
    "/chat-sessions/{session_id}",
    response_model=ChatSessionDetail,
    name="get_session",
)
def get_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Any:
    _assert_may_read_logs(db, user)

    session = db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    detail = ChatSessionDetail.model_validate(session)
    return detail.model_copy(
        update={
            "message_count": len(session.messages),
            "messages": sorted(session.messages, key=lambda m: m.created_at),
        }
    )
