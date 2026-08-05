import io
import re
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES, get_client_ip, get_current_user, get_db, require_role
from app.core.audit import log_audit
from app.core.email import send_email
from app.core.files import save_upload
from app.core.notifications import hr_user_ids, notify, notify_many
from app.models.document import DocumentCategory, DocumentStatus, EmployeeDocument
from app.models.employee import Employee
from app.models.mixins import utcnow
from app.models.notification import NotificationCategory
from app.models.user import User
from app.schemas.document import (
    DocumentCategoryCreate,
    DocumentCategoryResponse,
    DocumentCategoryUpdate,
    EmployeeDocumentResponse,
    VerifyDocumentRequest,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_category_or_404(db: Session, category_id: int, company_id: int | None) -> DocumentCategory:
    category = db.scalar(
        select(DocumentCategory).where(
            DocumentCategory.id == category_id,
            DocumentCategory.company_id == company_id,
            DocumentCategory.deleted_at.is_(None),
        )
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document category not found")
    return category


def _get_employee_for(db: Session, employee_id: int, company_id: int | None) -> Employee:
    employee = db.scalar(
        select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id, Employee.deleted_at.is_(None)
        )
    )
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


def _own_employee(db: Session, current_user: User) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))


# ---- Categories ----

@router.get("/categories", response_model=list[DocumentCategoryResponse])
def list_categories(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[DocumentCategory]:
    return list(
        db.scalars(
            select(DocumentCategory).where(
                DocumentCategory.company_id == current_user.company_id, DocumentCategory.deleted_at.is_(None)
            )
        )
    )


@router.post("/categories", response_model=DocumentCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: DocumentCategoryCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> DocumentCategory:
    category = DocumentCategory(
        company_id=current_user.company_id, name=payload.name, is_mandatory=payload.is_mandatory
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    log_audit(
        db,
        user_id=current_user.id,
        action="document_category_created",
        entity_type="document_category",
        entity_id=category.id,
        ip_address=get_client_ip(request),
    )
    return category


@router.put("/categories/{category_id}", response_model=DocumentCategoryResponse)
def update_category(
    category_id: int,
    payload: DocumentCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> DocumentCategory:
    category = _get_category_or_404(db, category_id, current_user.company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> None:
    category = _get_category_or_404(db, category_id, current_user.company_id)
    category.deleted_at = utcnow()
    db.commit()


# ---- Documents ----

@router.post("/upload", response_model=EmployeeDocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    request: Request,
    category_id: int = Form(...),
    employee_id: int | None = Form(None),
    expiry_date: date | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmployeeDocument:
    uploaded_on_behalf = employee_id is not None
    if uploaded_on_behalf:
        if current_user.role.value not in HR_WRITE_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        employee = _get_employee_for(db, employee_id, current_user.company_id)
    else:
        employee = _own_employee(db, current_user)
        if employee is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile linked to this account"
            )

    _get_category_or_404(db, category_id, current_user.company_id)

    saved = save_upload(current_user.company_id, employee.id, file)

    # Company-issued documents HR uploads on an employee's behalf (offer letters, etc.)
    # don't need a separate approval step - HR is already the authority issuing them.
    # Employee self-submitted documents (ID proofs, etc.) still require HR verification.
    document = EmployeeDocument(
        employee_id=employee.id,
        category_id=category_id,
        file_path=saved.file_path,
        file_name=saved.file_name,
        file_size=saved.file_size,
        mime_type=saved.mime_type,
        expiry_date=expiry_date,
        status=DocumentStatus.APPROVED if uploaded_on_behalf else DocumentStatus.PENDING,
        verified_by=current_user.id if uploaded_on_behalf else None,
        verified_at=utcnow() if uploaded_on_behalf else None,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    log_audit(
        db,
        user_id=current_user.id,
        action="document_uploaded",
        entity_type="employee_document",
        entity_id=document.id,
        ip_address=get_client_ip(request),
    )

    category = db.get(DocumentCategory, category_id)
    if uploaded_on_behalf:
        employee_user = db.get(User, employee.user_id)
        notify(
            db, user_id=employee_user.id, category=NotificationCategory.DOCUMENT,
            title="A new document was added to your file",
            body=f"{category.name if category else 'A document'} was uploaded and approved by HR.",
            link="/employee/documents",
        )
    else:
        notify_many(
            db, user_ids=hr_user_ids(db, current_user.company_id), category=NotificationCategory.DOCUMENT,
            title="Document awaiting verification",
            body=f"{current_user.full_name} uploaded {category.name if category else 'a document'} for review.",
            link=f"/hr/documents/employee/{employee.id}",
        )
    return document


@router.get("", response_model=list[EmployeeDocumentResponse])
def list_documents(
    employee_id: int | None = None,
    status_filter: DocumentStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EmployeeDocument]:
    is_hr = current_user.role.value in HR_WRITE_ROLES

    if is_hr:
        query = (
            select(EmployeeDocument)
            .join(Employee, Employee.id == EmployeeDocument.employee_id)
            .where(Employee.company_id == current_user.company_id, EmployeeDocument.deleted_at.is_(None))
        )
        if employee_id is not None:
            query = query.where(EmployeeDocument.employee_id == employee_id)
    else:
        employee = _own_employee(db, current_user)
        if employee is None:
            return []
        query = select(EmployeeDocument).where(
            EmployeeDocument.employee_id == employee.id, EmployeeDocument.deleted_at.is_(None)
        )

    if status_filter is not None:
        query = query.where(EmployeeDocument.status == status_filter)

    return list(db.scalars(query.order_by(EmployeeDocument.uploaded_at.desc())))


def _safe_component(value: str) -> str:
    return re.sub(r"[^\w\-]+", "_", value).strip("_") or "file"


@router.get("/employee/{employee_id}/zip")
def download_employee_documents_zip(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> StreamingResponse:
    employee = _get_employee_for(db, employee_id, current_user.company_id)
    employee_user = db.get(User, employee.user_id)

    documents = list(
        db.scalars(
            select(EmployeeDocument).where(
                EmployeeDocument.employee_id == employee.id, EmployeeDocument.deleted_at.is_(None)
            )
        )
    )
    if not documents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No documents found for this employee")

    buffer = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for document in documents:
            file_path = Path(document.file_path)
            if not file_path.exists():
                continue

            category = db.get(DocumentCategory, document.category_id)
            category_label = _safe_component(category.name if category else "document")
            original = Path(document.file_name)
            arcname = f"{category_label}{original.suffix}"

            suffix = 1
            while arcname in used_names:
                arcname = f"{category_label}_{suffix}{original.suffix}"
                suffix += 1
            used_names.add(arcname)

            zip_file.write(file_path, arcname=arcname)

    buffer.seek(0)
    zip_filename = f"{_safe_component(employee.employee_code)}_{_safe_component(employee_user.full_name)}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


def _get_document_or_404(db: Session, document_id: int) -> EmployeeDocument:
    document = db.scalar(
        select(EmployeeDocument).where(EmployeeDocument.id == document_id, EmployeeDocument.deleted_at.is_(None))
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


def _authorize_document_access(db: Session, document: EmployeeDocument, current_user: User) -> None:
    employee = db.get(Employee, document.employee_id)
    if employee is None or employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    is_owner = employee.user_id == current_user.id
    is_hr = current_user.role.value in HR_WRITE_ROLES
    if not is_owner and not is_hr:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


@router.get("/{document_id}/download")
def download_document(
    document_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> FileResponse:
    document = _get_document_or_404(db, document_id)
    _authorize_document_access(db, document, current_user)
    return FileResponse(document.file_path, filename=document.file_name, media_type=document.mime_type)


@router.post("/{document_id}/verify", response_model=EmployeeDocumentResponse)
def verify_document(
    document_id: int,
    payload: VerifyDocumentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> EmployeeDocument:
    document = _get_document_or_404(db, document_id)
    _authorize_document_access(db, document, current_user)

    document.status = payload.status
    document.verified_by = current_user.id
    document.verified_at = utcnow()
    document.review_notes = payload.notes
    db.commit()
    db.refresh(document)

    log_audit(
        db,
        user_id=current_user.id,
        action=f"document_{payload.status.value}",
        entity_type="employee_document",
        entity_id=document.id,
        ip_address=get_client_ip(request),
    )

    employee = db.get(Employee, document.employee_id)
    employee_user = db.get(User, employee.user_id)
    send_email(
        to=employee_user.email,
        subject=f"Document {payload.status.value}",
        body=f"Your document '{document.file_name}' has been {payload.status.value}.",
    )
    notify(
        db, user_id=employee_user.id, category=NotificationCategory.DOCUMENT,
        title=f"Document {payload.status.value}",
        body=f"Your document '{document.file_name}' has been {payload.status.value}.",
        link="/employee/documents",
    )
    return document
