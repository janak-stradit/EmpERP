from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES, get_client_ip, get_current_user, get_db, require_role
from app.core.audit import log_audit
from app.models.department import Department
from app.models.mixins import utcnow
from app.models.user import User
from app.schemas.department import DepartmentCreate, DepartmentResponse, DepartmentUpdate

router = APIRouter(prefix="/departments", tags=["departments"])


def _get_department_or_404(db: Session, department_id: int, company_id: int | None) -> Department:
    department = db.scalar(
        select(Department).where(
            Department.id == department_id,
            Department.company_id == company_id,
            Department.deleted_at.is_(None),
        )
    )
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    return department


@router.get("", response_model=list[DepartmentResponse])
def list_departments(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[Department]:
    return list(
        db.scalars(
            select(Department).where(
                Department.company_id == current_user.company_id, Department.deleted_at.is_(None)
            )
        )
    )


@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
def create_department(
    payload: DepartmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> Department:
    department = Department(
        company_id=current_user.company_id, name=payload.name, head_employee_id=payload.head_employee_id
    )
    db.add(department)
    db.commit()
    db.refresh(department)
    log_audit(
        db,
        user_id=current_user.id,
        action="department_created",
        entity_type="department",
        entity_id=department.id,
        ip_address=get_client_ip(request),
    )
    return department


@router.get("/{department_id}", response_model=DepartmentResponse)
def get_department(
    department_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Department:
    return _get_department_or_404(db, department_id, current_user.company_id)


@router.put("/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> Department:
    department = _get_department_or_404(db, department_id, current_user.company_id)
    if payload.name is not None:
        department.name = payload.name
    if payload.head_employee_id is not None:
        department.head_employee_id = payload.head_employee_id
    db.commit()
    db.refresh(department)
    log_audit(
        db,
        user_id=current_user.id,
        action="department_updated",
        entity_type="department",
        entity_id=department.id,
        ip_address=get_client_ip(request),
    )
    return department


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> None:
    department = _get_department_or_404(db, department_id, current_user.company_id)
    department.deleted_at = utcnow()
    db.commit()
    log_audit(
        db,
        user_id=current_user.id,
        action="department_deleted",
        entity_type="department",
        entity_id=department.id,
        ip_address=get_client_ip(request),
    )
