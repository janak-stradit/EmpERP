from datetime import date, datetime

from pydantic import BaseModel

from app.models.onboarding import OnboardingStatus, OnboardingTaskStatus
from app.models.user import UserRole


class OnboardingTaskCreate(BaseModel):
    title: str
    description: str | None = None
    assigned_to_role: UserRole = UserRole.EMPLOYEE
    due_days: int = 7
    is_mandatory: bool = True


class OnboardingTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    assigned_to_role: UserRole | None = None
    due_days: int | None = None
    is_mandatory: bool | None = None


class OnboardingTaskResponse(BaseModel):
    id: int
    template_id: int
    title: str
    description: str | None
    assigned_to_role: UserRole
    due_days: int
    is_mandatory: bool

    model_config = {"from_attributes": True}


class OnboardingTemplateCreate(BaseModel):
    name: str
    description: str | None = None


class OnboardingTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class OnboardingTemplateResponse(BaseModel):
    id: int
    company_id: int
    name: str
    description: str | None

    model_config = {"from_attributes": True}


class OnboardingTemplateDetail(OnboardingTemplateResponse):
    tasks: list[OnboardingTaskResponse]


class AssignOnboardingRequest(BaseModel):
    employee_id: int
    template_id: int


class EmployeeOnboardingTaskResponse(BaseModel):
    id: int
    task_id: int
    title: str
    status: OnboardingTaskStatus
    assigned_to_user_id: int | None
    due_date: date | None
    completed_at: datetime | None
    notes: str | None


class EmployeeOnboardingResponse(BaseModel):
    id: int
    employee_id: int
    template_id: int
    status: OnboardingStatus
    started_at: datetime | None
    completed_at: datetime | None
    progress_percent: float
    tasks: list[EmployeeOnboardingTaskResponse]


class UpdateOnboardingTaskStatusRequest(BaseModel):
    status: OnboardingTaskStatus
    notes: str | None = None
