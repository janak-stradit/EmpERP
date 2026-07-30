"""Idempotent seed script: creates the default company and first super admin user."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Company, User
from app.models.user import UserRole


def main() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == settings.super_admin_email))
        if existing is not None:
            print(f"Super admin '{settings.super_admin_email}' already exists. Skipping.")
            return

        if not settings.super_admin_password:
            raise SystemExit("SUPER_ADMIN_PASSWORD is not set in .env")

        company = db.scalar(select(Company).where(Company.name == settings.super_admin_company_name))
        if company is None:
            company = Company(name=settings.super_admin_company_name)
            db.add(company)
            db.flush()

        admin = User(
            company_id=company.id,
            email=settings.super_admin_email,
            password_hash=hash_password(settings.super_admin_password),
            full_name=settings.super_admin_name,
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_2fa_enabled=False,
        )
        db.add(admin)
        db.commit()
        print(f"Super admin '{settings.super_admin_email}' created (company: {company.name}).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
