import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, utcnow


class LeaveApplicationStatus(str, enum.Enum):
    PENDING_MANAGER = "pending_manager"
    PENDING_HR = "pending_hr"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LeaveApprovalAction(str, enum.Enum):
    SUBMITTED = "submitted"
    MANAGER_APPROVED = "manager_approved"
    MANAGER_REJECTED = "manager_rejected"
    HR_APPROVED = "hr_approved"
    HR_REJECTED = "hr_rejected"
    CANCELLED = "cancelled"


class LeaveType(SoftDeleteMixin, Base):
    __tablename__ = "leave_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    max_days_per_year: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    carry_forward_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_carry_forward_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    encashment_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_unpaid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    color_code: Mapped[str | None] = mapped_column(String(7), nullable=True)


class LeaveBalance(Base):
    __tablename__ = "leave_balances"
    __table_args__ = (UniqueConstraint("employee_id", "leave_type_id", "year", name="uq_leave_balance_employee_type_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id"), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    total_allocated: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    used: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    carried_forward: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    encashed: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    lapsed: Mapped[float] = mapped_column(Float, nullable=False, default=0)


class LeaveApplication(SoftDeleteMixin, Base):
    __tablename__ = "leave_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id"), nullable=False)
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[LeaveApplicationStatus] = mapped_column(
        Enum(LeaveApplicationStatus, name="leave_application_status"),
        nullable=False,
        default=LeaveApplicationStatus.PENDING_MANAGER,
    )
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    manager_action_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    manager_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hr_action_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    hr_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LeaveApprovalHistory(Base):
    __tablename__ = "leave_approval_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    leave_application_id: Mapped[int] = mapped_column(ForeignKey("leave_applications.id"), nullable=False, index=True)
    action_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[LeaveApprovalAction] = mapped_column(Enum(LeaveApprovalAction, name="leave_approval_action"), nullable=False)
    action_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
