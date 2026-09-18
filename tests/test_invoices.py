"""Invoices and the Wise payment flow — spec Sections 5.3.D and 12."""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_service import SettingKey, invalidate, set_setting
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.models.invoice import Invoice
from app.services.notification.backends import console_backend

PDF = b"%PDF-1.4 fake but plausible"
WISE_LINK = "https://wise.com/pay/business/smartaware"


@pytest.fixture(autouse=True)
def _reset() -> None:
    invalidate()
    console_backend.clear()


@pytest.fixture
def setup(api: TestClient, db: Session, make_user, login):
    make_user(UserRole.ADMIN, email="admin@example.com")
    manager, _ = make_user(UserRole.MANAGER, email="mgr@example.com")
    _user, client = make_user(
        UserRole.CLIENT,
        email="client@example.com",
        company_name="Acme Ltd",
        assigned_manager=manager,
    )
    _other_user, other = make_user(UserRole.CLIENT, email="other@example.com", company_name="Rival")
    set_setting(db, SettingKey.WISE_PAYMENT_LINK_BASE_URL, WISE_LINK)
    db.commit()
    return {
        "admin": login("admin@example.com"),
        "manager": login("mgr@example.com"),
        "client": login("client@example.com"),
        "other_client": login("other@example.com"),
        "client_id": client.id,
        "other_client_id": other.id,
    }


def _raise_invoice(api, setup, **overrides):
    body = {
        "client_id": str(setup["client_id"]),
        "service_description": "Self Assessment return, 2025/26",
        "amount": "500.00",
        "currency": "GBP",
        **overrides,
    }
    return api.post("/api/v1/admin/invoices", json=body, headers=setup["admin"])


# --- Raising one ------------------------------------------------------------------


def test_an_invoice_is_raised_against_a_client(api: TestClient, setup) -> None:
    response = _raise_invoice(api, setup)
    assert response.status_code == 201
    body = response.json()
    assert body["invoice_reference"].startswith("INV-")
    assert body["amount"] == "500.00"
    assert body["state"] == "unpaid"


def test_references_are_allocated_in_sequence(api: TestClient, setup) -> None:
    """The reference is the only thread back once the money is inside Wise, so
    it is allocated rather than left to whoever is typing."""
    first = _raise_invoice(api, setup).json()["invoice_reference"]
    second = _raise_invoice(api, setup).json()["invoice_reference"]
    assert first != second
    assert sorted([first, second]) == [first, second]


def test_a_reference_can_be_supplied_but_not_reused(api: TestClient, setup) -> None:
    assert _raise_invoice(api, setup, invoice_reference="SA-001").status_code == 201
    clash = _raise_invoice(api, setup, invoice_reference="SA-001")
    assert clash.status_code == 422
    assert "SA-001" in clash.json()["detail"]


def test_an_unknown_currency_is_refused(api: TestClient, setup) -> None:
    response = _raise_invoice(api, setup, currency="XXX")
    assert response.status_code == 422


def test_a_zero_amount_is_refused(api: TestClient, setup) -> None:
    assert _raise_invoice(api, setup, amount="0.00").status_code == 422


def test_a_manager_cannot_raise_one(api: TestClient, setup) -> None:
    """Section 12.4 keeps money decisions with the administrator."""
    response = api.post(
        "/api/v1/admin/invoices",
        json={
            "client_id": str(setup["client_id"]),
            "service_description": "Work",
            "amount": "10.00",
            "currency": "GBP",
        },
        headers=setup["manager"],
    )
    assert response.status_code == 403


def test_a_manager_can_read_their_clients_invoices(api: TestClient, setup) -> None:
    _raise_invoice(api, setup)
    rows = api.get("/api/v1/admin/invoices", headers=setup["manager"]).json()
    assert [r["invoice_reference"] for r in rows]


# --- What the client sees ---------------------------------------------------------


def test_a_client_sees_only_their_own(api: TestClient, setup) -> None:
    _raise_invoice(api, setup)
    mine = api.get("/api/v1/portal/invoices", headers=setup["client"]).json()
    assert len(mine) == 1
    assert api.get("/api/v1/portal/invoices", headers=setup["other_client"]).json() == []


def test_another_clients_invoice_is_not_found(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    response = api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=setup["other_client"])
    assert response.status_code == 404, "existence itself is a disclosure"


def test_the_client_view_withholds_the_staff_fields(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup, notes="Chase in a fortnight.").json()["id"]
    mine = api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=setup["client"]).json()
    assert "notes" not in mine
    assert "external_payment_ref" not in mine
    assert "reconciled_by" not in mine


def test_an_overdue_invoice_says_so(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup, due_date="2020-01-01").json()["id"]
    mine = api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=setup["client"]).json()
    assert mine["state"] == "overdue"
    assert mine["status"] == "unpaid", "the state is how it reads, the status is the money"


# --- Sharing the invoice file -----------------------------------------------------


def test_the_invoice_file_reaches_the_client_and_is_announced(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    response = api.post(
        f"/api/v1/admin/invoices/{invoice_id}/document",
        files={"file": ("INV-001.pdf", io.BytesIO(PDF), "application/pdf")},
        headers=setup["admin"],
    )
    assert response.status_code == 200
    assert response.json()["document"]["file_name"] == "INV-001.pdf"

    mine = api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=setup["client"]).json()
    assert mine["document"]["file_name"] == "INV-001.pdf"

    sent = console_backend.sent[-1]
    assert sent.to == "client@example.com"
    assert "INV-001.pdf" in sent.body

    # Filed as a document too, so it is where a client would also look for it.
    docs = api.get("/api/v1/portal/documents", headers=setup["client"]).json()
    assert [d["doc_type"] for d in docs] == ["invoice"]


def test_the_file_can_be_downloaded_by_the_client(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    api.post(
        f"/api/v1/admin/invoices/{invoice_id}/document",
        files={"file": ("INV-001.pdf", io.BytesIO(PDF), "application/pdf")},
        headers=setup["admin"],
    )
    document_id = api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=setup["client"]).json()[
        "document"
    ]["id"]

    content = api.get(f"/api/v1/portal/documents/{document_id}/content", headers=setup["client"])
    assert content.status_code == 200
    assert content.content == PDF


# --- Paying -----------------------------------------------------------------------


def test_the_pay_url_carries_the_amount_currency_and_reference(api: TestClient, setup) -> None:
    """Section 3 of the integration guide, and the only thread for Section 8."""
    invoice = _raise_invoice(api, setup, amount="1234.50", currency="GBP").json()
    response = api.post(f"/api/v1/portal/invoices/{invoice['id']}/pay", headers=setup["client"])
    assert response.status_code == 200
    url = response.json()["pay_url"]
    assert url.startswith(f"{WISE_LINK}?")
    assert "amount=1234.50" in url
    assert "currency=GBP" in url
    assert f"description={invoice['invoice_reference']}" in url


def test_starting_a_payment_does_not_make_it_paid(api: TestClient, db: Session, setup) -> None:
    """Opening Wise is not paying. An invoice that looked settled on the
    strength of a click would be worse than one that looked unpaid."""
    invoice_id = _raise_invoice(api, setup).json()["id"]
    api.post(f"/api/v1/portal/invoices/{invoice_id}/pay", headers=setup["client"])

    row = db.execute(select(Invoice).where(Invoice.id == invoice_id)).scalar_one()
    assert row.status.value == "unpaid"
    assert row.wise_payment_url, "the attempt is recorded, for matching by hand later"


def test_the_url_is_rebuilt_from_the_invoice_not_replayed(api: TestClient, setup) -> None:
    """A corrected amount must not stay payable at the old figure."""
    invoice_id = _raise_invoice(api, setup, amount="500.00").json()["id"]
    api.post(f"/api/v1/portal/invoices/{invoice_id}/pay", headers=setup["client"])

    api.patch(
        f"/api/v1/admin/invoices/{invoice_id}",
        json={"amount": "250.00"},
        headers=setup["admin"],
    )
    url = api.post(f"/api/v1/portal/invoices/{invoice_id}/pay", headers=setup["client"]).json()[
        "pay_url"
    ]
    assert "amount=250.00" in url and "amount=500.00" not in url


def test_pay_now_is_withheld_until_the_link_is_configured(
    api: TestClient, db: Session, setup
) -> None:
    set_setting(db, SettingKey.WISE_PAYMENT_LINK_BASE_URL, "")
    db.commit()
    invoice_id = _raise_invoice(api, setup).json()["id"]

    mine = api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=setup["client"]).json()
    assert mine["pay_url"] is None

    response = api.post(f"/api/v1/portal/invoices/{invoice_id}/pay", headers=setup["client"])
    assert response.status_code == 503
    assert "contact SmartAWARE" in response.json()["detail"]


def test_a_link_that_is_not_wise_is_treated_as_unset(api: TestClient, db: Session, setup) -> None:
    """The link is free text an administrator can edit, and following it asks
    someone for money. A typo should fail closed."""
    set_setting(db, SettingKey.WISE_PAYMENT_LINK_BASE_URL, "https://wise.com.evil.example/pay")
    db.commit()
    invoice_id = _raise_invoice(api, setup).json()["id"]
    mine = api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=setup["client"]).json()
    assert mine["pay_url"] is None


def test_a_plain_http_link_is_treated_as_unset(api: TestClient, db: Session, setup) -> None:
    set_setting(db, SettingKey.WISE_PAYMENT_LINK_BASE_URL, "http://wise.com/pay/business/x")
    db.commit()
    invoice_id = _raise_invoice(api, setup).json()["id"]
    assert (
        api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=setup["client"]).json()["pay_url"]
        is None
    )


def test_a_paid_invoice_cannot_be_paid_again(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    api.post(f"/api/v1/admin/invoices/{invoice_id}/mark-paid", json={}, headers=setup["admin"])
    response = api.post(f"/api/v1/portal/invoices/{invoice_id}/pay", headers=setup["client"])
    assert response.status_code == 409


# --- Sending the receipt back -----------------------------------------------------


def test_the_receipt_reaches_the_admin_and_the_assigned_manager(api: TestClient, setup) -> None:
    """Section 7 routes this more narrowly than a general upload: it is a
    request to check something, not news for the whole team."""
    invoice = _raise_invoice(api, setup).json()
    console_backend.clear()

    response = api.post(
        f"/api/v1/portal/invoices/{invoice['id']}/receipt",
        files={"file": ("wise-receipt.pdf", io.BytesIO(PDF), "application/pdf")},
        headers=setup["client"],
    )
    assert response.status_code == 201
    assert response.json()["receipt"]["file_name"] == "wise-receipt.pdf"

    recipients = sorted(m.to for m in console_backend.sent)
    assert recipients == ["admin@example.com", "mgr@example.com"]
    assert invoice["invoice_reference"] in console_backend.sent[0].body


def test_a_receipt_does_not_settle_the_invoice(api: TestClient, setup) -> None:
    """The client's proof is a claim. What settles it is someone reading the
    Wise account."""
    invoice_id = _raise_invoice(api, setup).json()["id"]
    api.post(
        f"/api/v1/portal/invoices/{invoice_id}/receipt",
        files={"file": ("r.pdf", io.BytesIO(PDF), "application/pdf")},
        headers=setup["client"],
    )
    mine = api.get(f"/api/v1/portal/invoices/{invoice_id}", headers=setup["client"]).json()
    assert mine["status"] == "unpaid"
    assert mine["state"] == "awaiting_confirmation", "the wait is ours, not theirs"


def test_a_client_cannot_attach_a_receipt_to_someone_elses_invoice(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    response = api.post(
        f"/api/v1/portal/invoices/{invoice_id}/receipt",
        files={"file": ("r.pdf", io.BytesIO(PDF), "application/pdf")},
        headers=setup["other_client"],
    )
    assert response.status_code == 404


# --- Settling ---------------------------------------------------------------------


def test_marking_paid_records_who_decided_and_why(api: TestClient, db: Session, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    response = api.post(
        f"/api/v1/admin/invoices/{invoice_id}/mark-paid",
        json={"external_payment_ref": "WISE-TX-77", "note": "Seen in the Wise account."},
        headers=setup["admin"],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "paid"
    assert body["external_payment_ref"] == "WISE-TX-77"
    assert body["reconciliation_method"] == "manual"
    assert body["reconciled_by"]

    entry = db.execute(select(AuditLog).where(AuditLog.action == "invoice.reconciled")).scalar_one()
    assert entry.entity_id == body["id"] or str(entry.entity_id) == body["id"]
    assert entry.new_value["external_payment_ref"] == "WISE-TX-77"


def test_a_manager_cannot_settle_an_invoice(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    response = api.post(
        f"/api/v1/admin/invoices/{invoice_id}/mark-paid", json={}, headers=setup["manager"]
    )
    assert response.status_code == 403


def test_a_client_cannot_settle_their_own_invoice(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    response = api.post(
        f"/api/v1/admin/invoices/{invoice_id}/mark-paid", json={}, headers=setup["client"]
    )
    assert response.status_code in (403, 404)


def test_a_paid_invoice_is_no_longer_editable(api: TestClient, setup) -> None:
    """It is a record of a transaction, not a draft. Correcting one means a
    credit note, which is an accounting decision rather than an edit."""
    invoice_id = _raise_invoice(api, setup).json()["id"]
    api.post(f"/api/v1/admin/invoices/{invoice_id}/mark-paid", json={}, headers=setup["admin"])
    response = api.patch(
        f"/api/v1/admin/invoices/{invoice_id}", json={"amount": "1.00"}, headers=setup["admin"]
    )
    assert response.status_code == 422


def test_marking_paid_twice_is_refused(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    api.post(f"/api/v1/admin/invoices/{invoice_id}/mark-paid", json={}, headers=setup["admin"])
    again = api.post(
        f"/api/v1/admin/invoices/{invoice_id}/mark-paid", json={}, headers=setup["admin"]
    )
    assert again.status_code == 409


def test_a_cancelled_invoice_cannot_be_settled(api: TestClient, setup) -> None:
    invoice_id = _raise_invoice(api, setup).json()["id"]
    api.post(f"/api/v1/admin/invoices/{invoice_id}/cancel", headers=setup["admin"])
    response = api.post(
        f"/api/v1/admin/invoices/{invoice_id}/mark-paid", json={}, headers=setup["admin"]
    )
    assert response.status_code == 409


def test_counts_are_scoped_to_the_caller(api: TestClient, setup) -> None:
    _raise_invoice(api, setup)
    _raise_invoice(api, setup, due_date="2020-01-01")

    mine = api.get("/api/v1/portal/invoices/counts", headers=setup["client"]).json()
    assert mine == {"unpaid": 2, "overdue": 1, "paid": 0, "cancelled": 0}

    theirs = api.get("/api/v1/portal/invoices/counts", headers=setup["other_client"]).json()
    assert theirs == {"unpaid": 0, "overdue": 0, "paid": 0, "cancelled": 0}


def test_anonymous_callers_are_refused_everywhere(api: TestClient) -> None:
    assert api.get("/api/v1/portal/invoices").status_code == 401
    assert api.get("/api/v1/admin/invoices").status_code == 401
