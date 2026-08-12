from datetime import date, time
from pydantic import BaseModel

class ActivityCategoryResponse(BaseModel):
    id: int
    name: str
    description: str | None

    model_config = {"from_attributes": True}

class ActivityLogCreate(BaseModel):
    category_id: int
    log_date: date
    time_block: time
    duration_minutes: int = 30
    is_overtime: bool = False
    notes: str | None = None

class ActivityLogUpdate(BaseModel):
    category_id: int
    log_date: date
    time_block: time
    duration_minutes: int = 30
    is_overtime: bool = False
    notes: str | None = None

class ActivityLogResponse(BaseModel):
    id: int
    employee_id: int
    category_id: int
    log_date: date
    time_block: time
    duration_minutes: int
    is_overtime: bool
    notes: str | None
    
    category: ActivityCategoryResponse | None = None

    model_config = {"from_attributes": True}

class CategoryHours(BaseModel):
    category_name: str
    hours: float

class EmployeeSummary(BaseModel):
    employee_id: int
    employee_name: str
    total_regular_hours: float
    total_overtime_hours: float
    categories: list[CategoryHours]
    statuses: dict[str, int] = {}

class DailyStatusUpdate(BaseModel):
    status: str
    notes: str | None = None

class DailyStatusResponse(BaseModel):
    id: int
    employee_id: int
    log_date: date
    status: str
    notes: str | None

    model_config = {"from_attributes": True}
