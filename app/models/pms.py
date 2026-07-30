import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, utcnow


class PmsReviewerRole(str, enum.Enum):
    SELF = "self"
    MANAGER = "manager"
    PEER = "peer"
    SUBORDINATE = "subordinate"


class PmsReviewRequestStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"


class PromotionRecommendationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Competency(SoftDeleteMixin, Base):
    __tablename__ = "competencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class RatingScale(SoftDeleteMixin, Base):
    __tablename__ = "rating_scales"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    min_score: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=5)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. {"1": "Needs improvement", "3": "Meets expectations", "5": "Outstanding"}
    descriptors_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PmsReviewRequest(Base):
    """Authorization gate: only a user with a pending request here may submit a review
    for (employee, cycle) in that role - prevents arbitrary users from rating each other."""

    __tablename__ = "pms_review_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("appraisal_cycles.id"), nullable=False, index=True)
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    reviewer_role: Mapped[PmsReviewerRole] = mapped_column(Enum(PmsReviewerRole, name="pms_reviewer_role"), nullable=False)
    status: Mapped[PmsReviewRequestStatus] = mapped_column(
        Enum(PmsReviewRequestStatus, name="pms_review_request_status"),
        nullable=False,
        default=PmsReviewRequestStatus.PENDING,
    )
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class PmsEvaluation(Base):
    __tablename__ = "pms_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("appraisal_cycles.id"), nullable=False, index=True)
    evaluator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    evaluator_role: Mapped[PmsReviewerRole] = mapped_column(Enum(PmsReviewerRole, name="pms_reviewer_role"), nullable=False)
    review_request_id: Mapped[int] = mapped_column(ForeignKey("pms_review_requests.id"), nullable=False, unique=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class PmsEvaluationItem(Base):
    __tablename__ = "pms_evaluation_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("pms_evaluations.id"), nullable=False, index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competencies.id"), nullable=False)
    rating: Mapped[float] = mapped_column(Float, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class PromotionRecommendation(Base):
    __tablename__ = "promotion_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("appraisal_cycles.id"), nullable=False, index=True)
    recommended_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    recommended_designation_id: Mapped[int | None] = mapped_column(ForeignKey("designations.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PromotionRecommendationStatus] = mapped_column(
        Enum(PromotionRecommendationStatus, name="promotion_recommendation_status"),
        nullable=False,
        default=PromotionRecommendationStatus.PENDING,
    )
