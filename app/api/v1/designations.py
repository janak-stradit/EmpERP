from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES, get_client_ip, get_current_user, get_db, require_role
from app.core.audit import log_audit
from app.models.designation import Designation
from app.models.mixins import utcnow
from app.models.user import User
from app.schemas.designation import DesignationCreate, DesignationResponse, DesignationUpdate

router = APIRouter(prefix="/designations", tags=["designations"])


def _get_designation_or_404(db: Session, designation_id: int, company_id: int | None) -> Designation:
    designation = db.scalar(
        select(Designation).where(
            Designation.id == designation_id,
            Designation.company_id == company_id,
            Designation.deleted_at.is_(None),
        )
    )
    if designation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Designation not found")
    return designation


@router.get("", response_model=list[DesignationResponse])
def list_designations(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[Designation]:
    return list(
        db.scalars(
            select(Designation).where(
                Designation.company_id == current_user.company_id, Designation.deleted_at.is_(None)
            )
        )
    )


@router.post("", response_model=DesignationResponse, status_code=status.HTTP_201_CREATED)
def create_designation(
    payload: DesignationCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> Designation:
    designation = Designation(company_id=current_user.company_id, name=payload.name, level=payload.level)
    db.add(designation)
    db.commit()
    db.refresh(designation)
    log_audit(
        db,
        user_id=current_user.id,
        action="designation_created",
        entity_type="designation",
        entity_id=designation.id,
        ip_address=get_client_ip(request),
    )
    return designation


@router.get("/{designation_id}", response_model=DesignationResponse)
def get_designation(
    designation_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Designation:
    return _get_designation_or_404(db, designation_id, current_user.company_id)


@router.put("/{designation_id}", response_model=DesignationResponse)
def update_designation(
    designation_id: int,
    payload: DesignationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> Designation:
    designation = _get_designation_or_404(db, designation_id, current_user.company_id)
    if payload.name is not None:
        designation.name = payload.name
    if payload.level is not None:
        designation.level = payload.level
    db.commit()
    db.refresh(designation)
    log_audit(
        db,
        user_id=current_user.id,
        action="designation_updated",
        entity_type="designation",
        entity_id=designation.id,
        ip_address=get_client_ip(request),
    )
    return designation


@router.delete("/{designation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_designation(
    designation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> None:
    designation = _get_designation_or_404(db, designation_id, current_user.company_id)
    designation.deleted_at = utcnow()
    db.commit()
    log_audit(
        db,
        user_id=current_user.id,
        action="designation_deleted",
        entity_type="designation",
        entity_id=designation.id,
        ip_address=get_client_ip(request),
    )
