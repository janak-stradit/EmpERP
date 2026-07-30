from datetime import date, datetime

from pydantic import BaseModel

from app.models.appraisal import AppraisalCycleStatus
from app.models.kra import KraStatus


# ---- Cycles (shared with PMS) ----

class AppraisalCycleCreate(BaseModel):
    name: str
    start_date: date
    end_date: date
    enabled_reviewer_roles: list[str] = ["self", "manager"]


class AppraisalCycleUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: AppraisalCycleStatus | None = None
    enabled_reviewer_roles: list[str] | None = None


class AppraisalCycleResponse(BaseModel):
    id: int
    company_id: int
    name: str
    start_date: date
    end_date: date
    status: AppraisalCycleStatus
    enabled_reviewer_roles: list[str]


# ---- KRA templates ----

class KraTemplateItemCreate(BaseModel):
    title: str
    description: str | None = None
    default_weightage: float = 0
    measurement_criteria: str | None = None


class KraTemplateItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    default_weightage: float | None = None
    measurement_criteria: str | None = None


class KraTemplateItemResponse(BaseModel):
    id: int
    template_id: int
    title: str
    description: str | None
    default_weightage: float
    measurement_criteria: str | None

    model_config = {"from_attributes": True}


class KraTemplateCreate(BaseModel):
    name: str
    description: str | None = None
    is_default: bool = False


class KraTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_default: bool | None = None


class KraTemplateResponse(BaseModel):
    id: int
    company_id: int
    name: str
    description: str | None
    is_default: bool

    model_config = {"from_attributes": True}


class KraTemplateDetail(KraTemplateResponse):
    items: list[KraTemplateItemResponse]


# ---- Employee KRA ----

class AssignKraRequest(BaseModel):
    employee_id: int
    cycle_id: int
    template_id: int


class EmployeeKraItemRatingUpdate(BaseModel):
    item_id: int
    rating: float
    comment: str | None = None


class SelfRatingRequest(BaseModel):
    items: list[EmployeeKraItemRatingUpdate]


class ManagerRatingRequest(BaseModel):
    items: list[EmployeeKraItemRatingUpdate]


class EmployeeKraItemResponse(BaseModel):
    id: int
    title: str
    description: str | None
    weightage: float
    target: str | None
    employee_rating: float | None
    employee_comment: str | None
    manager_rating: float | None
    manager_comment: str | None
    score: float | None


class EmployeeKraResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    employee_code: str
    cycle_id: int
    cycle_name: str
    template_id: int
    template_name: str
    status: KraStatus
    overall_score: float | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    approved_at: datetime | None


class EmployeeKraDetail(EmployeeKraResponse):
    items: list[EmployeeKraItemResponse]
