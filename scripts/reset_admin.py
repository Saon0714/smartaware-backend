"""Look at the Admin accounts on this database, and remove them.

    uv run python scripts/reset_admin.py                  # show them
    uv run python scripts/reset_admin.py --delete         # say what would go
    uv run python scripts/reset_admin.py --delete --yes   # remove them

    docker compose exec api uv run python scripts/reset_admin.py ...

For the case this exists to solve: somebody set up a local database, created
the bootstrap Admin, and has since lost both the address and the password. The
account cannot be recovered through the portal, because signing in is the
thing that is not working.

Run with no arguments first. It prints the addresses, which is often the whole
problem — a forgotten address and a forgotten password are different losses,
and only the second one needs anything destroyed. `--set-password` is there
for when the address turns out to be enough.

`--delete` is a dry run unless `--yes` follows it. Removing the only Admin
locks everybody out of the Admin Portal until `create_admin.py` runs, which is
fine when that is the plan and awful when it is a slip.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import audit_service  # noqa: E402

CREATE_HINT = "  uv run python scripts/create_admin.py --email you@example.com --generate"


def _describe(user: User) -> str:
    seen = f"{user.last_login_at:%Y-%m-%d}" if user.last_login_at else "never"
    return (
        f"  {user.email}\n"
        f"      name          {user.full_name or '—'}\n"
        f"      active        {user.is_active}\n"
        f"      created       {user.created_at:%Y-%m-%d}\n"
        f"      last sign-in  {seen}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or remove Admin accounts.")
    parser.add_argument("--delete", action="store_true", help="Remove the Admin account(s).")
    parser.add_argument(
        "--yes", action="store_true", help="Actually delete. Without it, --delete only reports."
    )
    parser.add_argument("--email", help="Limit to one account, when there is more than one.")
    parser.add_argument(
        "--set-password",
        nargs="?",
        const="",
        metavar="PASSWORD",
        help=(
            "Set a new password instead of deleting. Omit the value for a generated "
            "one. The account is forced to change it at next sign-in."
        ),
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        stmt = select(User).where(User.role == UserRole.ADMIN).order_by(User.created_at)
        if args.email:
            stmt = stmt.where(User.email == args.email.strip().lower())
        admins = list(db.execute(stmt).scalars())

        if not admins:
            if args.email:
                print(f"No Admin account with the address {args.email}.")
            else:
                print("There are no Admin accounts on this database.")
            print("\nCreate one with:")
            print(CREATE_HINT)
            return 1

        print(f"{len(admins)} Admin account(s):\n")
        for user in admins:
            print(_describe(user))
            print()

        if args.set_password is not None:
            if len(admins) > 1 and not args.email:
                print("More than one Admin — name which with --email.")
                return 1
            user = admins[0]
            password = args.set_password or secrets.token_urlsafe(16)
            user.hashed_password = hash_password(password)
            user.must_change_password = True
            user.is_active = True
            # Any session opened with the old password stops working, which is
            # the point: the password was lost, not necessarily unknown.
            user.token_version += 1
            audit_service.record(
                db,
                actor=None,
                action=audit_service.AuditAction.USER_PASSWORD_RESET,
                entity_type="user",
                entity_id=user.id,
                new_value={"email": user.email},
                reason="Reset from the console with scripts/reset_admin.py.",
            )
            db.commit()
            print(f"Password reset for {user.email}")
            if not args.set_password:
                print(f"Temporary password: {password}")
            print("This account must change its password at next sign-in.")
            return 0

        if not args.delete:
            print("Nothing changed. To remove these:")
            print("  uv run python scripts/reset_admin.py --delete --yes")
            print("\nOr, if the address above is enough and only the password is lost:")
            print("  uv run python scripts/reset_admin.py --set-password")
            return 0

        # An Admin should never own a client record, but the foreign key from
        # `clients.user_id` cascades, so a mislabelled row would take a client
        # and everything hanging off it. Refused rather than assumed.
        owning = [user for user in admins if user.client is not None]
        if owning:
            print("Refusing to delete — these Admin accounts own a client record:")
            for user in owning:
                print(f"  {user.email}")
            print(
                "\nDeleting one would destroy that client and every invoice, document,\n"
                "task and note belonging to it. Sort the role out first."
            )
            return 1

        if not args.yes:
            print("This would permanently delete the account(s) above.")
            print(
                "Their past actions stay in the record but lose the name attached to\n"
                "them — audit entries, uploads and reconciliations become unattributed."
            )
            print("\nNobody will be able to sign in to the Admin Portal until you run:")
            print(CREATE_HINT)
            print("\nRe-run with --yes to go ahead.")
            return 0

        for user in admins:
            audit_service.record(
                db,
                actor=None,
                action=audit_service.AuditAction.USER_DELETED,
                entity_type="user",
                entity_id=user.id,
                old_value={"email": user.email, "role": user.role.value},
                reason="Deleted from the console with scripts/reset_admin.py.",
            )
            db.delete(user)
        db.commit()

        print(f"Deleted {len(admins)} Admin account(s).")

    print("\nThere is now no way into the Admin Portal. Create the replacement:")
    print(CREATE_HINT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
