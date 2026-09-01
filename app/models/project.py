import enum
from datetime import date

from sqlalchemy import JSON, Boolean, Date, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin


class StatusCategory(str, enum.Enum):
    TODO = "todo"
    INPROGRESS = "inprogress"
    DONE = "done"


class SprintStatus(str, enum.Enum):
    FUTURE = "future"
    ACTIVE = "active"
    COMPLETED = "completed"
    CLOSED = "closed"


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("company_id", "key", name="uq_project_company_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Sprint capacity planning schedule. working_days uses Python's date.weekday()
    # convention: 0=Monday .. 6=Sunday.
    hours_per_day: Mapped[float] = mapped_column(Float, nullable=False, default=8.0)
    working_days: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=lambda: [0, 1, 2, 3, 4])


class ProjectMember(CreatedAtMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "employee_id", name="uq_project_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="developer")


class ProjectWatcher(CreatedAtMixin, Base):
    __tablename__ = "project_watchers"
    __table_args__ = (UniqueConstraint("project_id", "employee_id", name="uq_project_watcher"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)


class TicketStatus(Base):
    __tablename__ = "ticket_statuses"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_ticket_status_project_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[StatusCategory] = mapped_column(Enum(StatusCategory, name="status_category"), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6c757d")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    wip_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Sprint(TimestampMixin, Base):
    __tablename__ = "sprints"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SprintStatus] = mapped_column(
        Enum(SprintStatus, name="sprint_status"), nullable=False, default=SprintStatus.FUTURE
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    committed_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SprintProject(CreatedAtMixin, Base):
    """Additional projects linked to a sprint beyond its owning project (Sprint.project_id)."""

    __tablename__ = "sprint_projects"
    __table_args__ = (UniqueConstraint("sprint_id", "project_id", name="uq_sprint_project"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sprint_id: Mapped[int] = mapped_column(ForeignKey("sprints.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
