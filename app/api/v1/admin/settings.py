"""Admin: runtime settings.

These values change how the system behaves for everyone, so each write is
validated against both its stored type and the constraints in
`app.core.setting_schema`. A settings screen that accepts a nonsensical value
is worse than none: the failure surfaces later, somewhere unrelated.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require_permission
from app.core.permissions import Permission
from app.core.setting_schema import GROUP_LABELS, SETTING_SPECS
from app.core.settings_service import invalidate
from app.models.enums import SettingValueType
from app.models.setting import Setting
from app.schemas.setting import SettingGroupOut, SettingOut, SettingUpdate

router = APIRouter(prefix="/admin", tags=["admin-settings"])

_can_manage = Depends(require_permission(Permission.SETTINGS_MANAGE))

_email = TypeAdapter(EmailStr)


def _serialise(row: Setting) -> dict:
    spec = SETTING_SPECS.get(row.key)
    return {
        "key": row.key,
        "value": row.value,
        "value_type": row.value_type,
        "description": row.description,
        "group": row.group,
        "is_editable": row.is_editable,
        "updated_at": row.updated_at,
        "updated_by_id": row.updated_by_id,
        "control": spec.control if spec else "text",
        "label": spec.label if spec else row.key.replace("_", " ").capitalize(),
        "choices": ([{"value": v, "label": label} for v, label in spec.choices] if spec else []),
        "minimum": spec.minimum if spec else None,
        "maximum": spec.maximum if spec else None,
        "hint": spec.hint if spec else None,
        "unit": spec.unit if spec else None,
        "confirm": spec.confirm if spec else None,
    }


def _coerce(row: Setting, value: Any) -> Any:
    """Check a submitted value against the setting's type and constraints."""
    spec = SETTING_SPECS.get(row.key)

    if row.value_type is SettingValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="This setting expects true or false.",
            )
        return value

    if row.value_type in (SettingValueType.INTEGER, SettingValueType.FLOAT):
        # Reject bool explicitly: it is a subclass of int in Python, and a
        # toggle silently becoming 1 would be a confusing way to fail.
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="This setting expects a number.",
            )
        number = int(value) if row.value_type is SettingValueType.INTEGER else float(value)
        if spec:
            if spec.minimum is not None and number < spec.minimum:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Must be at least {spec.minimum}.",
                )
            if spec.maximum is not None and number > spec.maximum:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Must be no more than {spec.maximum}.",
                )
        return number

    if row.value_type is SettingValueType.STRING:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="This setting expects text.",
            )
        if spec and spec.choices:
            allowed = [v for v, _ in spec.choices]
            if value not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Must be one of: {', '.join(allowed)}.",
                )
        return value.strip()

    # JSON. The email lists are the case worth checking: a typo here means a
    # notification silently goes nowhere.
    if spec and spec.control == "email_list":
        if not isinstance(value, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="This setting expects a list of email addresses.",
            )
        cleaned: list[str] = []
        for entry in value:
            if not isinstance(entry, str) or not entry.strip():
                continue
            try:
                cleaned.append(_email.validate_python(entry.strip()))
            except ValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"“{entry}” is not a valid email address.",
                ) from exc
        # De-duplicated, order preserved.
        return list(dict.fromkeys(cleaned))

    return value


@router.get(
    "/settings",
    response_model=list[SettingGroupOut],
    dependencies=[_can_manage],
    name="list",
)
def list_settings(db: DbSession) -> Any:
    """Grouped, so related settings are edited together."""
    rows = db.execute(select(Setting).order_by(Setting.group, Setting.key)).scalars()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.group or "other", []).append(_serialise(row))

    order = list(GROUP_LABELS)
    return [
        {
            "group": group,
            "label": GROUP_LABELS.get(group, group.replace("_", " ").capitalize()),
            "settings": settings,
        }
        for group, settings in sorted(
            grouped.items(),
            key=lambda item: order.index(item[0]) if item[0] in order else len(order),
        )
    ]


@router.get(
    "/settings/{key}",
    response_model=SettingOut,
    dependencies=[_can_manage],
    name="get",
)
def get_setting(key: str, db: DbSession) -> Any:
    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown setting.")
    return _serialise(row)


@router.patch(
    "/settings/{key}",
    response_model=SettingOut,
    dependencies=[_can_manage],
    name="update",
)
def update_setting(key: str, payload: SettingUpdate, user: CurrentUser, db: DbSession) -> Any:
    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row is None:
        # Settings are seeded, never created here — an unknown key is a typo or
        # a stale client, not a new setting.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown setting.")

    if not row.is_editable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This setting cannot be changed from the Admin Portal.",
        )

    row.value = _coerce(row, payload.value)
    row.updated_by_id = user.id
    db.commit()
    db.refresh(row)

    # The read cache is per-process and short-lived, but clearing it here means
    # the change is visible on the very next request rather than up to the TTL
    # later — which would look like the save had not worked.
    invalidate(key)
    return _serialise(row)
