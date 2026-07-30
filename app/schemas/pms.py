from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.pms import PmsReviewerRole, PmsReviewRequestStatus, PromotionRecommendationStatus


class CompetencyCreate(BaseModel):
    name: str
    category: str | None = None
    description: str | None = None


class CompetencyUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None


class CompetencyResponse(BaseModel):
    id: int
    company_id: int
    name: str
    category: str | None
    description: str | None

    model_config = {"from_attributes": True}


class RatingScaleCreate(BaseModel):
    name: str
    min_score: float = 1
    max_score: float = 5
    description: str | None = None
    descriptors: dict[str, str] | None = None


class RatingScaleUpdate(BaseModel):
    name: str | None = None
    min_score: float | None = None
    max_score: float | None = None
    description: str | None = None
    descriptors: dict[str, str] | None = None


class RatingScaleResponse(BaseModel):
    id: int
    company_id: int
    name: str
    min_score: float
    max_score: float
    description: str | None
    descriptors: dict[str, str] | None


class AssignEmployeeRequest(BaseModel):
    employee_id: int


class AssignReviewerRequest(BaseModel):
    employee_id: int
    reviewer_user_id: int
    reviewer_role: Literal["peer", "subordinate"]


class PmsReviewRequestResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    employee_code: str
    cycle_id: int
    cycle_name: str
    reviewer_role: PmsReviewerRole
    status: PmsReviewRequestStatus
    requested_at: datetime


class SubmitEvaluationItem(BaseModel):
    competency_id: int
    rating: float
    comment: str | None = None


class SubmitEvaluationRequest(BaseModel):
    review_request_id: int
    items: list[SubmitEvaluationItem]


class PmsEvaluationItemResponse(BaseModel):
    competency_id: int
    competency_name: str
    rating: float
    comment: str | None


class PmsEvaluationResponse(BaseModel):
    id: int
    employee_id: int
    cycle_id: int
    evaluator_id: int
    evaluator_name: str
    evaluator_role: PmsReviewerRole
    submitted_at: datetime
    items: list[PmsEvaluationItemResponse]


class CompletionRow(BaseModel):
    employee_id: int
    employee_name: str
    employee_code: str
    total_requests: int
    completed_requests: int


class NormalizationBucket(BaseModel):
    label: str
    band_min: float
    band_max: float
    count: int


class EmployeeNormalizationRow(BaseModel):
    employee_id: int
    employee_name: str
    employee_code: str
    manager_average: float | None


class NormalizationResponse(BaseModel):
    buckets: list[NormalizationBucket]
    employees: list[EmployeeNormalizationRow]


class PromotionRecommendationCreate(BaseModel):
    employee_id: int
    cycle_id: int
    recommended_designation_id: int | None = None
    reason: str | None = None


class PromotionRecommendationUpdate(BaseModel):
    status: PromotionRecommendationStatus


class PromotionRecommendationResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    employee_code: str
    cycle_id: int
    cycle_name: str
    recommended_by: int
    recommended_by_name: str
    recommended_designation_id: int | None
    recommended_designation_name: str | None
    reason: str | None
    status: PromotionRecommendationStatus
