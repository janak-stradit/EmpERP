import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin


class KraStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    REVIEWED = "reviewed"
    APPROVED = "approved"


class KraTemplate(SoftDeleteMixin, Base):
    __tablename__ = "kra_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class KraTemplateItem(Base):
    __tablename__ = "kra_template_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("kra_templates.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_weightage: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    measurement_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)


class EmployeeKra(SoftDeleteMixin, Base):
    __tablename__ = "employee_kras"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("appraisal_cycles.id"), nullable=False, index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("kra_templates.id"), nullable=False)
    status: Mapped[KraStatus] = mapped_column(Enum(KraStatus, name="kra_status"), nullable=False, default=KraStatus.DRAFT)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmployeeKraItem(Base):
    __tablename__ = "employee_kra_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_kra_id: Mapped[int] = mapped_column(ForeignKey("employee_kras.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weightage: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    employee_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    manager_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
