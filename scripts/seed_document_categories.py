"""Idempotent seed script: creates realistic default document categories for the default company."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Company, DocumentCategory

DEFAULT_CATEGORIES = [
    ("Government ID Proof (Aadhar/Passport/Voter ID)", True),
    ("PAN Card", True),
    ("Address Proof", True),
    ("Passport-size Photograph", True),
    ("10th Standard Certificate", True),
    ("12th Standard Certificate", True),
    ("Degree Certificate", True),
    ("Previous Employer Experience Letter", False),
    ("Previous Employer Relieving Letter", False),
    ("Last 3 Months Salary Slips", False),
    ("Signed Offer Letter", True),
    ("Bank Passbook / Cancelled Cheque", True),
    # Company-issued documents - typically uploaded by HR/Admin on behalf of the employee
    ("Offer Letter (Company Copy)", False),
    ("Compensation Plan", False),
    ("Employment Confirmation Letter", False),
]


def main() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        company = db.scalar(select(Company).where(Company.name == settings.super_admin_company_name))
        if company is None:
            raise SystemExit(
                f"Company '{settings.super_admin_company_name}' not found. Run scripts/seed_super_admin.py first."
            )

        existing_names = {
            name
            for (name,) in db.execute(
                select(DocumentCategory.name).where(DocumentCategory.company_id == company.id)
            ).all()
        }

        created = 0
        for name, is_mandatory in DEFAULT_CATEGORIES:
            if name in existing_names:
                continue
            db.add(DocumentCategory(company_id=company.id, name=name, is_mandatory=is_mandatory))
            created += 1

        db.commit()
        print(f"Created {created} document categories for '{company.name}' ({len(DEFAULT_CATEGORIES) - created} already existed).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
