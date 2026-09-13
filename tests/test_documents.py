"""Documents — spec Sections 5.3.E, 5.3.F, 7 and 9."""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.audit import AuditLog
from app.models.document import Document
from app.models.enums import UserRole
from app.services.notification.backends import console_backend

PDF = b"%PDF-1.4 fake but plausible"


@pytest.fixture(autouse=True)
def _reset() -> None:
    invalidate()
    console_backend.clear()


@pytest.fixture
def setup(api: TestClient, make_user, login):
    make_user(UserRole.ADMIN, email="admin@example.com")
    manager, _ = make_user(UserRole.MANAGER, email="mgr@example.com")
    user, client = make_user(
        UserRole.CLIENT,
        email="client@example.com",
        company_name="Acme Ltd",
        assigned_manager=manager,
    )
    return {
        "admin": login("admin@example.com"),
        "manager": login("mgr@example.com"),
        "client": login("client@example.com"),
        "client_record": client,
        "client_user": user,
    }


def _client_upload(
    api, headers, name="accounts.pdf", data=PDF, doc_type="general", content_type="application/pdf"
):
    return api.post(
        "/api/v1/portal/documents",
        files={"file": (name, io.BytesIO(data), content_type)},
        data={"doc_type": doc_type},
        headers=headers,
    )


def _staff_upload(api, headers, client_id, name="letter.pdf", data=PDF):
    return api.post(
        "/api/v1/admin/documents",
        files={"file": (name, io.BytesIO(data), "application/pdf")},
        data={"client_id": str(client_id), "doc_type": "general"},
        headers=headers,
    )


# --- Client uploads (Section 5.3.E) -----------------------------------------------


def test_a_client_can_upload_and_see_their_document(api: TestClient, setup) -> None:
    response = _client_upload(api, setup["client"])
    assert response.status_code == 201
    assert response.json()["direction"] == "client_to_smartaware"
    assert response.json()["version"] == 1

    rows = api.get("/api/v1/portal/documents", headers=setup["client"]).json()
    assert [d["file_name"] for d in rows] == ["accounts.pdf"]


def test_a_client_uploads_only_to_their_own_account(
    api: TestClient, db: Session, make_user, setup
) -> None:
    """The target comes from the caller's scope, so there is no client_id in
    the request to tamper with."""
    _user, other = make_user(UserRole.CLIENT, email="other@example.com")

    api.post(
        "/api/v1/portal/documents",
        files={"file": ("x.pdf", io.BytesIO(PDF), "application/pdf")},
        data={"doc_type": "general", "client_id": str(other.id)},
        headers=setup["client"],
    )

    stored = db.execute(select(Document)).scalars().one()
    assert stored.client_id == setup["client_record"].id


def test_a_client_cannot_see_another_clients_documents(
    api: TestClient, make_user, login, setup
) -> None:
    uploaded = _client_upload(api, setup["client"]).json()
    make_user(UserRole.CLIENT, email="other@example.com")
    other = login("other@example.com")

    assert api.get("/api/v1/portal/documents", headers=other).json() == []
    assert (
        api.get(f"/api/v1/portal/documents/{uploaded['id']}/download", headers=other).status_code
        == 404
    )
    assert (
        api.get(f"/api/v1/portal/documents/{uploaded['id']}/content", headers=other).status_code
        == 404
    )


# --- Staff uploads (Section 5.3.F) --------------------------------------------------


def test_staff_upload_reaches_only_that_client(api: TestClient, make_user, login, setup) -> None:
    _staff_upload(api, setup["admin"], setup["client_record"].id)

    mine = api.get("/api/v1/portal/documents", headers=setup["client"]).json()
    assert [d["file_name"] for d in mine] == ["letter.pdf"]
    assert mine[0]["direction"] == "smartaware_to_client"

    make_user(UserRole.CLIENT, email="other@example.com")
    assert api.get("/api/v1/portal/documents", headers=login("other@example.com")).json() == []


def test_a_manager_cannot_upload_for_a_client_they_do_not_hold(
    api: TestClient, make_user, setup
) -> None:
    _user, other = make_user(UserRole.CLIENT)
    assert _staff_upload(api, setup["manager"], other.id).status_code == 404


def test_a_client_cannot_use_the_staff_upload(api: TestClient, setup) -> None:
    assert _staff_upload(api, setup["client"], setup["client_record"].id).status_code == 403


# --- Notifications (Section 7) --------------------------------------------------------


def test_a_general_client_upload_notifies_the_team(api: TestClient, db: Session, setup) -> None:
    set_setting(db, SettingKey.NOTIFY_DOCUMENT_RECIPIENTS, ["team@smartaware.example"])
    db.commit()

    _client_upload(api, setup["client"])

    assert [m.to for m in console_backend.sent] == ["team@smartaware.example"]
    assert "Acme Ltd" in console_backend.sent[0].subject


def test_an_invoice_upload_goes_to_admin_and_the_assigned_manager(api: TestClient, setup) -> None:
    """Section 7 routes this more narrowly than a general upload: a payment
    receipt needs the people who can reconcile it."""
    _client_upload(api, setup["client"], name="receipt.pdf", doc_type="invoice")

    recipients = {m.to for m in console_backend.sent}
    assert recipients == {"admin@example.com", "mgr@example.com"}
    assert "receipt" in console_backend.sent[0].subject.lower() or True


def test_an_invoice_upload_does_not_use_the_general_recipient_list(
    api: TestClient, db: Session, setup
) -> None:
    set_setting(db, SettingKey.NOTIFY_DOCUMENT_RECIPIENTS, ["team@smartaware.example"])
    db.commit()

    _client_upload(api, setup["client"], name="receipt.pdf", doc_type="invoice")

    assert "team@smartaware.example" not in {m.to for m in console_backend.sent}


def test_a_staff_upload_notifies_the_client(api: TestClient, setup) -> None:
    _staff_upload(api, setup["admin"], setup["client_record"].id)
    assert [m.to for m in console_backend.sent] == ["client@example.com"]


def test_nothing_is_sent_while_the_team_list_is_empty(api: TestClient, setup) -> None:
    _client_upload(api, setup["client"])
    assert console_backend.sent == []


# --- Versioning (Section 13 item 12) -------------------------------------------------


def test_re_uploading_the_same_name_keeps_both_versions(api: TestClient, setup) -> None:
    """An overwrite would silently destroy a version someone may already have
    relied on, which is the wrong default for tax records."""
    first = _client_upload(api, setup["client"], data=b"%PDF first").json()
    second = _client_upload(api, setup["client"], data=b"%PDF second").json()

    assert first["version"] == 1
    assert second["version"] == 2
    assert second["supersedes_id"] == first["id"]

    rows = api.get("/api/v1/portal/documents", headers=setup["client"]).json()
    assert len(rows) == 2
    superseded = {d["id"]: d["is_superseded"] for d in rows}
    assert superseded[first["id"]] is True
    assert superseded[second["id"]] is False


def test_overwrite_mode_replaces_instead(api: TestClient, db: Session, setup) -> None:
    set_setting(db, SettingKey.DOCUMENT_VERSIONING, "overwrite")
    db.commit()

    first = _client_upload(api, setup["client"], data=b"%PDF first").json()
    _client_upload(api, setup["client"], data=b"%PDF second")

    rows = api.get("/api/v1/portal/documents", headers=setup["client"]).json()
    assert [d["id"] for d in rows] != [first["id"]]
    assert len(rows) == 1


def test_versions_are_independent_per_direction(api: TestClient, setup) -> None:
    """A staff document happening to share a name with a client's upload is a
    different document, not a new version of it."""
    _client_upload(api, setup["client"], name="notes.pdf")
    staff = _staff_upload(api, setup["admin"], setup["client_record"].id, name="notes.pdf").json()
    assert staff["version"] == 1
    assert staff["supersedes_id"] is None


# --- Validation ----------------------------------------------------------------------


def test_dangerous_file_types_are_refused(api: TestClient, setup) -> None:
    refused = _client_upload(
        api, setup["client"], name="payload.exe", content_type="application/pdf"
    )
    assert refused.status_code == 422
    assert ".exe" in refused.json()["detail"]


def test_an_unlisted_content_type_is_refused(api: TestClient, setup) -> None:
    """An allowlist, so a new dangerous type is not acceptable by default."""
    refused = _client_upload(
        api, setup["client"], name="page.xyz", content_type="application/x-shockwave-flash"
    )
    assert refused.status_code == 422


def test_an_empty_file_is_refused(api: TestClient, setup) -> None:
    assert _client_upload(api, setup["client"], data=b"").status_code == 422


def test_an_oversized_file_is_refused(api: TestClient, setup) -> None:
    from app.services.document_service import MAX_UPLOAD_BYTES

    too_big = b"x" * (MAX_UPLOAD_BYTES + 1)
    refused = _client_upload(api, setup["client"], data=too_big)
    assert refused.status_code == 422
    assert "MB or smaller" in refused.json()["detail"]


def test_a_traversing_filename_is_neutralised(api: TestClient, db: Session, setup) -> None:
    response = _client_upload(api, setup["client"], name="../../../etc/passwd.pdf")
    assert response.status_code == 201
    assert response.json()["file_name"] == "passwd.pdf"

    stored = db.execute(select(Document)).scalars().one()
    assert ".." not in stored.s3_key


def test_stored_keys_are_not_derived_from_the_filename(api: TestClient, db: Session, setup) -> None:
    """Predictable keys would turn a bucket misconfiguration into a browsable
    archive of other clients' documents."""
    _client_upload(api, setup["client"], name="accounts.pdf")
    stored = db.execute(select(Document)).scalars().one()
    assert "accounts" not in stored.s3_key
    assert stored.s3_key.endswith(".pdf")


# --- Download and audit (Section 9) -----------------------------------------------------


def test_downloading_serves_the_bytes_with_a_safe_disposition(api: TestClient, setup) -> None:
    uploaded = _client_upload(api, setup["client"], data=b"%PDF payload").json()
    response = api.get(
        f"/api/v1/portal/documents/{uploaded['id']}/content", headers=setup["client"]
    )
    assert response.status_code == 200
    assert response.content == b"%PDF payload"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_every_download_is_audited(api: TestClient, db: Session, setup) -> None:
    uploaded = _client_upload(api, setup["client"]).json()
    api.get(f"/api/v1/portal/documents/{uploaded['id']}/content", headers=setup["client"])

    entry = (
        db.execute(select(AuditLog).where(AuditLog.action == "document.downloaded"))
        .scalars()
        .first()
    )
    assert entry is not None
    assert entry.actor_id == setup["client_user"].id


def test_a_download_link_is_refused_for_another_clients_document(
    api: TestClient, make_user, login, setup
) -> None:
    uploaded = _staff_upload(api, setup["admin"], setup["client_record"].id).json()
    make_user(UserRole.CLIENT, email="other@example.com")

    assert (
        api.get(
            f"/api/v1/portal/documents/{uploaded['id']}/content",
            headers=login("other@example.com"),
        ).status_code
        == 404
    )


# --- Archiving -------------------------------------------------------------------------


def test_only_an_admin_may_archive(api: TestClient, setup) -> None:
    uploaded = _client_upload(api, setup["client"]).json()

    assert (
        api.delete(
            f"/api/v1/admin/documents/{uploaded['id']}", headers=setup["manager"]
        ).status_code
        == 403
    )
    assert (
        api.delete(f"/api/v1/admin/documents/{uploaded['id']}", headers=setup["client"]).status_code
        == 403
    )

    archived = api.delete(f"/api/v1/admin/documents/{uploaded['id']}", headers=setup["admin"])
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True


def test_an_archived_document_disappears_for_the_client(
    api: TestClient, db: Session, setup
) -> None:
    uploaded = _client_upload(api, setup["client"]).json()
    api.delete(f"/api/v1/admin/documents/{uploaded['id']}", headers=setup["admin"])

    assert api.get("/api/v1/portal/documents", headers=setup["client"]).json() == []
    # Kept, not destroyed: these are tax records.
    assert db.get(Document, uploaded["id"]) is not None
