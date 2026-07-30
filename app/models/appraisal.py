import enum
from datetime import date

from sqlalchemy import JSON, Date, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin


class AppraisalCycleStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class AppraisalCycle(SoftDeleteMixin, Base):
    """Shared umbrella cycle used by both KRA and PMS modules."""

    __tablename__ = "appraisal_cycles"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AppraisalCycleStatus] = mapped_column(
        Enum(AppraisalCycleStatus, name="appraisal_cycle_status"), nullable=False, default=AppraisalCycleStatus.DRAFT
    )
    # PMS reviewer roles enabled for this cycle, e.g. {"enabled_roles": ["self", "manager", "peer", "subordinate"]}
    review_stages_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
