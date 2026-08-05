from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class TeamMapping(TimestampMixin, Base):
    __tablename__ = "team_mappings"
    __table_args__ = (
        UniqueConstraint("employee_id", "manager_id", name="uq_team_mapping_emp_mgr"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
