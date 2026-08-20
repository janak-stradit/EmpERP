from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, SoftDeleteMixin, TimestampMixin, utcnow


class IssueType(Base):
    __tablename__ = "issue_types"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_issue_type_company_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    icon: Mapped[str] = mapped_column(String(50), nullable=False, default="bi-bookmark")
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6c757d")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TicketPriority(Base):
    __tablename__ = "ticket_priorities"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_ticket_priority_company_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    icon: Mapped[str] = mapped_column(String(50), nullable=False, default="bi-dash")
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6c757d")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Ticket(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("project_id", "ticket_key", name="uq_ticket_project_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    ticket_key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    issue_type_id: Mapped[int] = mapped_column(ForeignKey("issue_types.id"), nullable=False)
    status_id: Mapped[int] = mapped_column(ForeignKey("ticket_statuses.id"), nullable=False, index=True)
    priority_id: Mapped[int | None] = mapped_column(ForeignKey("ticket_priorities.id"), nullable=True)

    reporter_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)

    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True, index=True)
    epic_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True, index=True)
    sprint_id: Mapped[int | None] = mapped_column(ForeignKey("sprints.id"), nullable=True, index=True)
    board_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    story_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TicketComment(SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TicketAttachment(CreatedAtMixin, Base):
    __tablename__ = "ticket_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)


class TicketActivity(Base):
    __tablename__ = "ticket_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class TicketWatcher(CreatedAtMixin, Base):
    __tablename__ = "ticket_watchers"
    __table_args__ = (UniqueConstraint("ticket_id", "employee_id", name="uq_ticket_watcher"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)


class Label(Base):
    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_label_project_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6c757d")


class TicketLabel(Base):
    __tablename__ = "ticket_labels"
    __table_args__ = (UniqueConstraint("ticket_id", "label_id", name="uq_ticket_label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id"), nullable=False, index=True)


class WorkLog(CreatedAtMixin, Base):
    __tablename__ = "work_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    minutes_spent: Mapped[int] = mapped_column(Integer, nullable=False)
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
