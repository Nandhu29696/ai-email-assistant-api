"""Create (or reset) an admin user — e.g. the first login on a fresh database.

    python -m scripts.create_admin                       # user "admin", generated password (printed once)
    python -m scripts.create_admin --username alice --email alice@example.com --password "S3cure-pass-123"

An existing user with that username is made an active admin and gets the new password.
"""
from __future__ import annotations

import argparse
import os
import secrets
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.user import User  # noqa: E402
from app.routers.auth import hash_password, validate_password_strength  # noqa: E402


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
            return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--email", default="admin@mailai.local")
    parser.add_argument("--full-name", default="Administrator")
    parser.add_argument("--password", help="omit to generate a strong one")
    args = parser.parse_args()

    password = args.password or generate_password()
    try:
        validate_password_strength(password)
    except Exception as exc:
        print(f"Password rejected: {getattr(exc, 'detail', exc)}")
        return 1

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == args.username).first()
        created = user is None
        if created:
            if db.query(User.id).filter(User.email == args.email).first():
                print(f"Another user already uses {args.email}; pass a different --email.")
                return 1
            user = User(username=args.username, email=args.email, full_name=args.full_name)
            db.add(user)
        user.hashed_password = hash_password(password)
        user.role = "admin"
        user.is_active = True
        db.commit()
    finally:
        db.close()

    print(f"{'Created' if created else 'Updated'} admin user '{args.username}'.")
    if not args.password:
        print(f"Generated password (shown once, change it under Settings): {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
