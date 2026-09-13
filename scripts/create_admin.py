"""Create the first Admin account.

Nobody can invite the first Admin, so it is bootstrapped here and run once at
deploy. The account is forced to change its password at first login, so the
value passed in is a handover credential and never a lasting one.

    uv run python scripts/create_admin.py --email a@b.com [--password ... | --generate]

Respects the `allow_multiple_admins` setting (Section 13 item 4): with it False,
a second Admin is refused rather than silently created.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.core.settings_service import SettingKey, get_setting  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the bootstrap Admin user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="Omit with --generate to get a random one.")
    parser.add_argument("--generate", action="store_true", help="Generate a random password.")
    parser.add_argument("--full-name", default="SmartAWARE Admin")
    args = parser.parse_args()

    if not args.password and not args.generate:
        parser.error("provide --password or --generate")

    password = args.password or secrets.token_urlsafe(16)
    email = args.email.strip().lower()

    with SessionLocal() as db:
        if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
            print(f"A user with email {email} already exists. Nothing to do.")
            return 1

        existing_admins = db.execute(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
        ).scalar_one()

        if existing_admins and not get_setting(db, SettingKey.ALLOW_MULTIPLE_ADMINS, False):
            print(
                f"An Admin already exists ({existing_admins} found) and "
                "'allow_multiple_admins' is False.\n"
                "Enable that setting in the Admin Portal first if additional "
                "Admins should be supported (spec Section 13 item 4)."
            )
            return 1

        db.add(
            User(
                email=email,
                full_name=args.full_name,
                hashed_password=hash_password(password),
                role=UserRole.ADMIN,
                is_active=True,
                must_change_password=True,
            )
        )
        db.commit()

    print(f"Created Admin: {email}")
    if args.generate:
        print(f"Temporary password: {password}")
    print("This account must change its password at first login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
