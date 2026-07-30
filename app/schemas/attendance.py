from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel

from app.models.attendance import AttendanceStatus, RegularizationStatus


class ShiftCreate(BaseModel):
    name: str
    start_time: time
    end_time: time
    grace_period_minutes: int = 10
    is_night_shift: bool = False


class ShiftUpdate(BaseModel):
    name: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    grace_period_minutes: int | None = None
    is_night_shift: bool | None = None


class ShiftResponse(BaseModel):
    id: int
    company_id: int
    name: str
    start_time: time
    end_time: time
    grace_period_minutes: int
    is_night_shift: bool

    model_config = {"from_attributes": True}


class AssignShiftRequest(BaseModel):
    employee_id: int
    effective_from: date


class EmployeeShiftResponse(BaseModel):
    id: int
    employee_id: int
    shift_id: int
    shift_name: str
    effective_from: date
    effective_to: date | None


class ClockInRequest(BaseModel):
    latitude: float | None = None
    longitude: float | None = None


class ClockOutRequest(BaseModel):
    latitude: float | None = None
    longitude: float | None = None


class AttendanceLogResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    employee_code: str
    date: date
    clock_in: datetime | None
    clock_out: datetime | None
    status: AttendanceStatus
    work_hours: float | None


class TodayStatusResponse(BaseModel):
    clocked_in: bool
    clocked_out: bool
    clock_in: datetime | None
    clock_out: datetime | None
    status: AttendanceStatus | None


class AttendanceReportRow(BaseModel):
    employee_id: int
    employee_name: str
    employee_code: str
    present_days: int
    late_days: int
    half_days: int
    total_hours: float


class RegularizationCreate(BaseModel):
    date: date
    requested_clock_in: datetime | None = None
    requested_clock_out: datetime | None = None
    reason: str


class RegularizationActionRequest(BaseModel):
    action: Literal["approve", "reject"]


class RegularizationResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    employee_code: str
    date: date
    requested_clock_in: datetime | None
    requested_clock_out: datetime | None
    reason: str
    status: RegularizationStatus
    approved_by: int | None
    approved_at: datetime | None
