from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentCategoryCreate(BaseModel):
    name: str
    is_mandatory: bool = False


class DocumentCategoryUpdate(BaseModel):
    name: str | None = None
    is_mandatory: bool | None = None


class DocumentCategoryResponse(BaseModel):
    id: int
    company_id: int
    name: str
    is_mandatory: bool

    model_config = {"from_attributes": True}


class EmployeeDocumentResponse(BaseModel):
    id: int
    employee_id: int
    category_id: int
    file_name: str
    file_size: int
    mime_type: str
    uploaded_at: datetime
    expiry_date: date | None
    status: DocumentStatus
    verified_by: int | None
    verified_at: datetime | None
    review_notes: str | None

    model_config = {"from_attributes": True}


class VerifyDocumentRequest(BaseModel):
    status: Literal[DocumentStatus.APPROVED, DocumentStatus.REJECTED]
    notes: str | None = None
