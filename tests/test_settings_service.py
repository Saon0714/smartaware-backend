"""Runtime settings: the Section 13 defaults must be data, not code."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import settings_service
from app.core.settings_service import SettingKey, get_setting, set_setting
from app.models.setting import Setting


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    settings_service.invalidate()


def test_section_13_defaults_are_seeded(seeded_db: Session) -> None:
    # Measured against the seeded FAQ rather than guessed — see the setting's
    # description for the observed relevant/irrelevant separation.
    assert get_setting(seeded_db, SettingKey.CHAT_SIMILARITY_THRESHOLD) == 0.35
    assert get_setting(seeded_db, SettingKey.INVITE_EXPIRY_DAYS) == 3
    assert get_setting(seeded_db, SettingKey.ALLOW_MULTIPLE_ADMINS) is False
    assert get_setting(seeded_db, SettingKey.MANAGER_CLIENT_SCOPE) == "assigned"
    assert get_setting(seeded_db, SettingKey.MANAGER_CAN_MANAGE_CONTENT) is False
    assert get_setting(seeded_db, SettingKey.DOCUMENT_VERSIONING) == "keep"
    assert get_setting(seeded_db, SettingKey.MFA_REQUIRED_ROLES) == []


def test_defaults_are_editable_without_a_deploy(seeded_db: Session) -> None:
    set_setting(seeded_db, SettingKey.CHAT_SIMILARITY_THRESHOLD, 0.6)
    assert get_setting(seeded_db, SettingKey.CHAT_SIMILARITY_THRESHOLD) == 0.6


def test_setting_write_invalidates_cache(seeded_db: Session) -> None:
    assert get_setting(seeded_db, SettingKey.INVITE_EXPIRY_DAYS) == 3
    set_setting(seeded_db, SettingKey.INVITE_EXPIRY_DAYS, 7)
    assert get_setting(seeded_db, SettingKey.INVITE_EXPIRY_DAYS) == 7


def test_unknown_setting_cannot_be_created_by_write(seeded_db: Session) -> None:
    with pytest.raises(KeyError):
        set_setting(seeded_db, "not_a_real_setting", 1)


def test_assumed_defaults_are_documented_for_admins(seeded_db: Session) -> None:
    """Anyone changing an assumption should see that it was one."""
    rows = seeded_db.execute(
        select(Setting).where(
            Setting.key.in_(
                [
                    SettingKey.CHAT_SIMILARITY_THRESHOLD,
                    SettingKey.MANAGER_CLIENT_SCOPE,
                    SettingKey.ALLOW_MULTIPLE_ADMINS,
                    SettingKey.DOCUMENT_VERSIONING,
                ]
            )
        )
    ).scalars()
    for row in rows:
        assert row.description and "ASSUMED DEFAULT" in row.description


def test_wise_link_is_unset_so_pay_now_stays_disabled(seeded_db: Session) -> None:
    """Spec 12: the Open Payment Link is copied from Wise by hand. Until
    SmartAWARE provides it there is nothing to redirect to."""
    assert get_setting(seeded_db, SettingKey.WISE_PAYMENT_LINK_BASE_URL) == ""
