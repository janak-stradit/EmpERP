from pydantic import BaseModel


class DepartmentCreate(BaseModel):
    name: str
    head_employee_id: int | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = None
    head_employee_id: int | None = None


class DepartmentResponse(BaseModel):
    id: int
    company_id: int
    name: str
    head_employee_id: int | None

    model_config = {"from_attributes": True}
