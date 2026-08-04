from pydantic import BaseModel

class TeamMappingCreate(BaseModel):
    employee_id: int
    manager_id: int

class TeamMappingResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    manager_id: int
    manager_name: str

    model_config = {"from_attributes": True}
