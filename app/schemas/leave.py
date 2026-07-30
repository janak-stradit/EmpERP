from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.models.leave import LeaveApplicationStatus, LeaveApprovalAction


class LeaveTypeCreate(BaseModel):
    name: str
    code: str
    max_days_per_year: float = 0
    carry_forward_allowed: bool = False
    max_carry_forward_days: float | None = None
    encashment_allowed: bool = False
    is_unpaid: bool = False
    color_code: str | None = None


class LeaveTypeUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    max_days_per_year: float | None = None
    carry_forward_allowed: bool | None = None
    max_carry_forward_days: float | None = None
    encashment_allowed: bool | None = None
    is_unpaid: bool | None = None
    color_code: str | None = None


class LeaveTypeResponse(BaseModel):
    id: int
    company_id: int
    name: str
    code: str
    max_days_per_year: float
    carry_forward_allowed: bool
    max_carry_forward_days: float | None
    encashment_allowed: bool
    is_unpaid: bool
    color_code: str | None

    model_config = {"from_attributes": True}


class LeaveBalanceResponse(BaseModel):
    id: int
    employee_id: int
    leave_type_id: int
    leave_type_name: str
    year: int
    total_allocated: float
    used: float
    carried_forward: float
    encashed: float
    lapsed: float
    remaining: float


class CompanyLeaveBalanceResponse(LeaveBalanceResponse):
    employee_name: str
    employee_code: str


class AllocateBalancesRequest(BaseModel):
    leave_type_id: int
    year: int
    total_days: float


class AllocateBalancesResponse(BaseModel):
    created: int
    skipped: int


class AdjustBalanceRequest(BaseModel):
    leave_type_id: int
    year: int
    total_allocated: float | None = None
    carried_forward: float | None = None
    encashed: float | None = None
    lapsed: float | None = None


class LeaveApplicationResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    employee_code: str
    leave_type_id: int
    leave_type_name: str
    from_date: date
    to_date: date
    days: float
    reason: str | None
    has_attachment: bool
    status: LeaveApplicationStatus
    applied_at: datetime
    manager_action_by: int | None
    manager_action_at: datetime | None
    hr_action_by: int | None
    hr_action_at: datetime | None
    rejection_reason: str | None


class LeaveApprovalHistoryResponse(BaseModel):
    id: int
    action_by_name: str | None
    action: LeaveApprovalAction
    action_at: datetime
    comments: str | None


class LeaveApplicationDetail(LeaveApplicationResponse):
    history: list[LeaveApprovalHistoryResponse]


class LeaveActionRequest(BaseModel):
    action: Literal["approve", "reject"]
    comments: str | None = None
