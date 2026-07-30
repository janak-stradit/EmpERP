from pydantic import BaseModel


class DesignationCreate(BaseModel):
    name: str
    level: int = 0


class DesignationUpdate(BaseModel):
    name: str | None = None
    level: int | None = None


class DesignationResponse(BaseModel):
    id: int
    company_id: int
    name: str
    level: int

    model_config = {"from_attributes": True}
