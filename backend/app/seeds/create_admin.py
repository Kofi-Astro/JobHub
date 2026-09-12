"""Create (or promote) an admin account.

    python -m app.seeds.create_admin --email a@x.com --password '...' --role superadmin

There is deliberately no public admin-registration endpoint — this CLI is how
the first admin (and any subsequent one) gets provisioned, by whoever has shell
access to the deployment (an operator action, not a self-serve signup).
"""

from __future__ import annotations

import argparse
import getpass

from sqlalchemy import select

from app.db.session import session_scope
from app.logging import configure_logging, get_logger
from app.models import AdminProfile, User
from app.models.enums import AdminRole, UserRole
from app.services.auth import hash_password

log = get_logger(__name__)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Create or promote an admin user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="omit to be prompted (safer: avoids shell history)")
    parser.add_argument(
        "--role",
        choices=[r.value for r in AdminRole],
        default=AdminRole.SUPERADMIN.value,
    )
    parser.add_argument("--full-name", default=None)
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters.")

    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == args.email))
        if user is None:
            user = User(
                role=UserRole.ADMIN,
                email=args.email,
                password_hash=hash_password(password),
                full_name=args.full_name,
                is_email_verified=True,
            )
            db.add(user)
            db.flush()
            action = "created"
        else:
            user.role = UserRole.ADMIN
            user.password_hash = hash_password(password)
            action = "promoted to admin / password reset"

        if user.admin_profile is None:
            db.add(AdminProfile(user_id=user.id, admin_role=AdminRole(args.role)))
        else:
            user.admin_profile.admin_role = AdminRole(args.role)

    log.info("admin.provisioned", email=args.email, role=args.role, action=action)
    print(f"OK: {args.email} {action} with role={args.role}")


if __name__ == "__main__":
    main()
