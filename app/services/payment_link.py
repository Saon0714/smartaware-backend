"""Building the Wise payment URL — spec Section 12.1.

The URL is assembled here from live invoice data and never stored as the
source of truth: an invoice whose amount is corrected must not still offer a
link to the old figure.

No Wise API call is involved, and none may be added. Wise's public API does not
support creating payment links, so the integration guide's instruction is
explicit: use the Open Payment Link and append the amount, currency and
reference. Everything below is string construction.
"""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode, urlparse

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.settings_service import SettingKey, get_setting
from app.models.invoice import Invoice

#: Where a Pay Now button is allowed to send someone.
#:
#: The link is free text an administrator can edit, and following it hands a
#: person a form asking for money. A typo should fail closed rather than send a
#: client somewhere unexpected wearing SmartAWARE's name. Wise's regional sites
#: all sit under this domain; a genuine need for another belongs in this list,
#: deliberately, rather than in whatever was pasted into a settings box.
ALLOWED_HOSTS = ("wise.com",)


class PaymentLinkUnavailable(Exception):
    """No usable Open Payment Link is configured."""


def configured_base(db: Session) -> str | None:
    """The Open Payment Link, or None while there is not a usable one.

    The settings row wins so SmartAWARE can change it without a deploy; the
    environment is the fallback, which is where the link is supplied on first
    install. Either way an unusable value reads as "not configured" rather than
    being offered to a client.
    """
    candidates = (
        str(get_setting(db, SettingKey.WISE_PAYMENT_LINK_BASE_URL, "") or ""),
        settings.WISE_PAYMENT_LINK_BASE_URL or "",
    )
    for candidate in candidates:
        base = candidate.strip()
        if base and _is_usable(base):
            return base.rstrip("?&")
    return None


def _is_usable(base: str) -> bool:
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    host = parsed.netloc.split("@")[-1].split(":")[0].lower()
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_HOSTS)


def for_invoice(db: Session, invoice: Invoice) -> str | None:
    """The URL a Pay Now button should open, or None while Pay Now is off.

    `description` carries the invoice reference because that is the only thread
    back to this invoice once the money is inside Wise. Section 8 of the
    integration guide is blunt about it: generating the link is the easy half,
    matching the payment is the part that has to be right.
    """
    base = configured_base(db)
    if base is None:
        return None

    query = urlencode(
        {
            "amount": _amount(invoice.amount),
            "currency": invoice.currency,
            "description": invoice.invoice_reference,
        }
    )
    separator = "&" if urlparse(base).query else "?"
    return f"{base}{separator}{query}"


def _amount(amount: Decimal) -> str:
    """Two decimal places, no thousands separators and no currency symbol —
    what a query parameter can carry without being re-interpreted."""
    return f"{Decimal(amount):.2f}"
