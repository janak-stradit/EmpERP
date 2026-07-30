import enum
from datetime import date

from sqlalchemy import JSON, Date, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class EmployeeStatus(str, enum.Enum):
    PROBATION = "probation"
    ACTIVE = "active"
    TERMINATED = "terminated"
    RESIGNED = "resigned"


class Employee(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    employee_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    designation_id: Mapped[int | None] = mapped_column(ForeignKey("designations.id"), nullable=True)
    reporting_manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)

    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    probation_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[EmployeeStatus] = mapped_column(
        Enum(EmployeeStatus, name="employee_status"), nullable=False, default=EmployeeStatus.PROBATION
    )

    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    personal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    emergency_contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    emergency_contact_relation: Mapped[str | None] = mapped_column(String(100), nullable=True)

    bank_account_number_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bank_ifsc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_account_holder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_account_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    profile_photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Super Admin-configured dashboard module override. Null = use standard role-based
    # access; a list here fully replaces the role-based default (always includes "profile").
    module_access_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
