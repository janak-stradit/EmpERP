"""Set the super admin password to a known value."""
 
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
    target_email = "admin@emperp.dev"
    new_password = "3vsfzECrPc4uV3Xt"
    db = SessionLocal()

    try:
        user = db.scalar(select(User).where(User.email == target_email))
        if user is None:
            company = db.scalar(select(Company).where(Company.name == settings.super_admin_company_name))
            if company is None:
                company = Company(name=settings.super_admin_company_name)
                db.add(company)
                db.flush()

            user = User(
                company_id=company.id,
                email=target_email,
                password_hash=hash_password(new_password),
                full_name=settings.super_admin_name,
                role=UserRole.SUPER_ADMIN,
                is_active=True,
                is_2fa_enabled=False,
            )
            db.add(user)
            db.commit()
            print(f"Super admin '{target_email}' created with password '{new_password}'.")
            return

        user.password_hash = hash_password(new_password)
        db.commit()
        print(f"Password updated for super admin '{target_email}'.")
    finally:
        db.close()
 
 
if __name__ == "__main__":
    main()
 
 