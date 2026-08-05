from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES, get_client_ip, get_current_user, get_db, require_role
from app.core.audit import log_audit
from app.core.email import send_email
from app.core.files import delete_file_if_exists, save_profile_photo
from app.core.modules import MODULE_CATALOG, effective_modules_for
from app.core.security import decrypt_secret, encrypt_secret, hash_password
from app.models.employee import Employee
from app.models.mixins import utcnow
from app.models.user import User
from app.schemas.employee import (
    ASSIGNABLE_EMPLOYEE_ROLES,
    EmployeeAccessUpdate,
    EmployeeAdminUpdate,
    EmployeeCreate,
    EmployeeDetail,
    EmployeeListItem,
    EmployeePasswordReset,
    EmployeeSelfUpdate,
    ModuleAccessUpdate,
)

router = APIRouter(prefix="/employees", tags=["employees"])

PROFILE_COMPLETION_FIELDS = (
    "phone",
    "personal_email",
    "date_of_birth",
    "gender",
    "address",
    "emergency_contact_name",
    "emergency_contact_phone",
    "emergency_contact_relation",
    "bank_account_number_encrypted",
    "bank_ifsc",
    "bank_name",
    "bank_account_holder_name",
    "bank_branch_name",
    "bank_account_type",
    "profile_photo_path",
)


def _profile_completion_percent(employee: Employee) -> int:
    filled = sum(1 for field in PROFILE_COMPLETION_FIELDS if getattr(employee, field))
    return round(filled / len(PROFILE_COMPLETION_FIELDS) * 100)


def _is_manager(db: Session, employee_id: int) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(Employee)
        .where(Employee.reporting_manager_id == employee_id, Employee.deleted_at.is_(None))
    )
    return (count or 0) > 0


def _to_detail(db: Session, employee: Employee, user: User) -> EmployeeDetail:
    bank_account_number = decrypt_secret(employee.bank_account_number_encrypted) if employee.bank_account_number_encrypted else None

    reporting_manager_name = None
    if employee.reporting_manager_id:
        manager = db.get(Employee, employee.reporting_manager_id)
        if manager:
            manager_user = db.get(User, manager.user_id)
            reporting_manager_name = manager_user.full_name if manager_user else None

    return EmployeeDetail(
        id=employee.id,
        user_id=user.id,
        company_id=employee.company_id,
        employee_code=employee.employee_code,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        department_id=employee.department_id,
        designation_id=employee.designation_id,
        reporting_manager_id=employee.reporting_manager_id,
        reporting_manager_name=reporting_manager_name,
        is_manager=_is_manager(db, employee.id),
        joining_date=employee.joining_date,
        probation_end_date=employee.probation_end_date,
        status=employee.status,
        is_active=user.is_active,
        phone=employee.phone,
        personal_email=employee.personal_email,
        date_of_birth=employee.date_of_birth,
        gender=employee.gender,
        address=employee.address,
        emergency_contact_name=employee.emergency_contact_name,
        emergency_contact_phone=employee.emergency_contact_phone,
        emergency_contact_relation=employee.emergency_contact_relation,
        bank_account_number=bank_account_number,
        bank_ifsc=employee.bank_ifsc,
        bank_name=employee.bank_name,
        bank_account_holder_name=employee.bank_account_holder_name,
        bank_branch_name=employee.bank_branch_name,
        bank_account_type=employee.bank_account_type,
        has_profile_photo=bool(employee.profile_photo_path),
        profile_completion_percent=_profile_completion_percent(employee),
        module_access=employee.module_access_json,
        enabled_modules=effective_modules_for(employee.module_access_json, user.role.value, _is_manager(db, employee.id)),
    )


def _get_employee_or_404(db: Session, employee_id: int, company_id: int | None) -> Employee:
    employee = db.scalar(
        select(Employee).where(
            Employee.id == employee_id,
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
        )
    )
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


def _get_own_employee_or_404(db: Session, current_user: User) -> Employee:
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile linked to this account")
    return employee


def _next_employee_code(db: Session, company_id: int) -> str:
    count = db.scalar(select(func.count()).select_from(Employee).where(Employee.company_id == company_id))
    return f"EMP{(count or 0) + 1:04d}"


@router.get("", response_model=list[EmployeeListItem])
def list_employees(
    db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> list[EmployeeListItem]:
    rows = db.execute(
        select(Employee, User)
        .join(User, User.id == Employee.user_id)
        .where(Employee.company_id == current_user.company_id, Employee.deleted_at.is_(None))
    ).all()

    manager_ids = {
        manager_id
        for (manager_id,) in db.execute(
            select(Employee.reporting_manager_id).where(
                Employee.company_id == current_user.company_id,
                Employee.deleted_at.is_(None),
                Employee.reporting_manager_id.is_not(None),
            )
        ).all()
    }

    return [
        EmployeeListItem(
            id=employee.id,
            employee_code=employee.employee_code,
            full_name=user.full_name,
            email=user.email,
            role=user.role,
            department_id=employee.department_id,
            designation_id=employee.designation_id,
            status=employee.status,
            is_active=user.is_active,
            is_manager=employee.id in manager_ids,
            joining_date=employee.joining_date,
        )
        for employee, user in rows
    ]


@router.post("", response_model=EmployeeDetail, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> EmployeeDetail:
    if payload.role not in ASSIGNABLE_EMPLOYEE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be one of {[r.value for r in ASSIGNABLE_EMPLOYEE_ROLES]}",
        )

    if db.scalar(select(User).where(User.email == payload.email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    user = User(
        company_id=current_user.company_id,
        email=payload.email,
        password_hash=hash_password(payload.initial_password),
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    employee = Employee(
        user_id=user.id,
        company_id=current_user.company_id,
        employee_code=_next_employee_code(db, current_user.company_id),
        department_id=payload.department_id,
        designation_id=payload.designation_id,
        reporting_manager_id=payload.reporting_manager_id,
        joining_date=payload.joining_date,
        probation_end_date=payload.probation_end_date,
        phone=payload.phone,
        personal_email=payload.personal_email,
        date_of_birth=payload.date_of_birth,
        gender=payload.gender,
        address=payload.address,
        emergency_contact_name=payload.emergency_contact_name,
        emergency_contact_phone=payload.emergency_contact_phone,
        emergency_contact_relation=payload.emergency_contact_relation,
        bank_account_number_encrypted=encrypt_secret(payload.bank_account_number)
        if payload.bank_account_number
        else None,
        bank_ifsc=payload.bank_ifsc,
        bank_name=payload.bank_name,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    db.refresh(user)

    log_audit(
        db,
        user_id=current_user.id,
        action="employee_created",
        entity_type="employee",
        entity_id=employee.id,
        ip_address=get_client_ip(request),
    )
    send_email(
        to=user.email,
        subject="Welcome to Stradit Workforce",
        body=f"Hi {user.full_name}, your account has been created. Employee code: {employee.employee_code}.",
    )
    return _to_detail(db, employee, user)


@router.get("/me", response_model=EmployeeDetail)
def get_my_employee_profile(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> EmployeeDetail:
    employee = _get_own_employee_or_404(db, current_user)
    return _to_detail(db, employee, current_user)


@router.put("/me", response_model=EmployeeDetail)
def update_my_employee_profile(
    payload: EmployeeSelfUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmployeeDetail:
    employee = _get_own_employee_or_404(db, current_user)
    updates = payload.model_dump(exclude_unset=True)
    if "bank_account_number" in updates:
        raw = updates.pop("bank_account_number")
        employee.bank_account_number_encrypted = encrypt_secret(raw) if raw else None
    for field, value in updates.items():
        setattr(employee, field, value)
    db.commit()
    db.refresh(employee)
    log_audit(
        db,
        user_id=current_user.id,
        action="employee_self_updated",
        entity_type="employee",
        entity_id=employee.id,
        ip_address=get_client_ip(request),
    )
    return _to_detail(db, employee, current_user)


@router.post("/me/photo", response_model=EmployeeDetail)
def upload_my_photo(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmployeeDetail:
    employee = _get_own_employee_or_404(db, current_user)

    saved = save_profile_photo(employee.company_id, employee.id, file)
    delete_file_if_exists(employee.profile_photo_path)
    employee.profile_photo_path = saved.file_path
    db.commit()
    db.refresh(employee)

    log_audit(
        db,
        user_id=current_user.id,
        action="employee_photo_updated",
        entity_type="employee",
        entity_id=employee.id,
        ip_address=get_client_ip(request),
    )
    return _to_detail(db, employee, current_user)


@router.get("/module-catalog")
def get_module_catalog(current_user: User = Depends(get_current_user)) -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label in MODULE_CATALOG.items()]


@router.get("/{employee_id}/photo")
def get_employee_photo(
    employee_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> FileResponse:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    if employee.user_id != current_user.id and current_user.role.value not in HR_WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    if not employee.profile_photo_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile photo set")
    return FileResponse(employee.profile_photo_path)


@router.get("/{employee_id}", response_model=EmployeeDetail)
def get_employee(
    employee_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> EmployeeDetail:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    if employee.user_id != current_user.id and current_user.role.value not in HR_WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    user = db.get(User, employee.user_id)
    return _to_detail(db, employee, user)


@router.put("/{employee_id}", response_model=EmployeeDetail)
def update_employee(
    employee_id: int,
    payload: EmployeeAdminUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> EmployeeDetail:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    user = db.get(User, employee.user_id)

    updates = payload.model_dump(exclude_unset=True)
    if "bank_account_number" in updates:
        raw = updates.pop("bank_account_number")
        employee.bank_account_number_encrypted = encrypt_secret(raw) if raw else None

    if updates.get("reporting_manager_id") == employee.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An employee cannot be their own manager")

    if "role" in updates:
        new_role = updates.pop("role")
        if new_role not in ASSIGNABLE_EMPLOYEE_ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"role must be one of {[r.value for r in ASSIGNABLE_EMPLOYEE_ROLES]}",
            )
        if user.id == current_user.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot change your own role")
        user.role = new_role

    for field, value in updates.items():
        setattr(employee, field, value)
    db.commit()
    db.refresh(employee)
    db.refresh(user)
    log_audit(
        db,
        user_id=current_user.id,
        action="employee_updated",
        entity_type="employee",
        entity_id=employee.id,
        ip_address=get_client_ip(request),
    )
    return _to_detail(db, employee, user)


@router.put("/{employee_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_employee_password(
    employee_id: int,
    payload: EmployeePasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> None:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    user = db.get(User, employee.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee user account not found")

    user.password_hash = hash_password(payload.new_password)
    db.commit()

    log_audit(
        db,
        user_id=current_user.id,
        action="employee_password_reset",
        entity_type="employee",
        entity_id=employee.id,
        ip_address=get_client_ip(request),
    )


@router.put("/{employee_id}/access", response_model=EmployeeDetail)
def update_employee_access(
    employee_id: int,
    payload: EmployeeAccessUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> EmployeeDetail:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    user = db.get(User, employee.user_id)

    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot change your own account access")

    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)

    log_audit(
        db,
        user_id=current_user.id,
        action="employee_activated" if payload.is_active else "employee_deactivated",
        entity_type="employee",
        entity_id=employee.id,
        ip_address=get_client_ip(request),
    )
    return _to_detail(db, employee, user)


@router.put("/{employee_id}/module-access", response_model=EmployeeDetail)
def update_employee_module_access(
    employee_id: int,
    payload: ModuleAccessUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
) -> EmployeeDetail:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    user = db.get(User, employee.user_id)

    if payload.modules is None:
        employee.module_access_json = None
    else:
        invalid = sorted(set(payload.modules) - set(MODULE_CATALOG))
        if invalid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown module(s): {invalid}")
        employee.module_access_json = sorted(set(payload.modules) | {"profile"})

    db.commit()
    db.refresh(employee)

    log_audit(
        db,
        user_id=current_user.id,
        action="employee_module_access_updated",
        entity_type="employee",
        entity_id=employee.id,
        ip_address=get_client_ip(request),
    )
    return _to_detail(db, employee, user)


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(
    employee_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> None:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    employee.deleted_at = utcnow()
    db.commit()
    log_audit(
        db,
        user_id=current_user.id,
        action="employee_deleted",
        entity_type="employee",
        entity_id=employee.id,
        ip_address=get_client_ip(request),
    )
