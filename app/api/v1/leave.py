from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES, get_client_ip, get_current_user, get_db, require_role
from app.core.audit import log_audit
from app.core.email import send_email
from app.core.files import save_leave_attachment
from app.core.notifications import hr_user_ids, notify, notify_many
from app.models.employee import Employee
from app.models.leave import (
    LeaveApplication,
    LeaveApplicationStatus,
    LeaveApprovalAction,
    LeaveApprovalHistory,
    LeaveBalance,
    LeaveType,
)
from app.models.mixins import utcnow
from app.models.notification import NotificationCategory
from app.models.user import User, UserRole
from app.schemas.leave import (
    AdjustBalanceRequest,
    AllocateBalancesRequest,
    AllocateBalancesResponse,
    CompanyLeaveBalanceResponse,
    LeaveActionRequest,
    LeaveApplicationDetail,
    LeaveApplicationResponse,
    LeaveApprovalHistoryResponse,
    LeaveBalanceResponse,
    LeaveTypeCreate,
    LeaveTypeResponse,
    LeaveTypeUpdate,
)

router = APIRouter(prefix="/leave", tags=["leave"])


# ---- Helpers ----

def _get_own_employee_or_404(db: Session, current_user: User) -> Employee:
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile linked to this account")
    return employee


def _get_employee_or_404(db: Session, employee_id: int, company_id: int | None) -> Employee:
    employee = db.scalar(
        select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id, Employee.deleted_at.is_(None)
        )
    )
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


def _get_leave_type_or_404(db: Session, leave_type_id: int, company_id: int | None) -> LeaveType:
    leave_type = db.scalar(
        select(LeaveType).where(
            LeaveType.id == leave_type_id, LeaveType.company_id == company_id, LeaveType.deleted_at.is_(None)
        )
    )
    if leave_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave type not found")
    return leave_type


def _get_application_or_404(db: Session, application_id: int) -> LeaveApplication:
    application = db.scalar(
        select(LeaveApplication).where(LeaveApplication.id == application_id, LeaveApplication.deleted_at.is_(None))
    )
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave application not found")
    return application


def _current_employee_or_none(db: Session, current_user: User) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))


def _authorize_application_access(db: Session, employee: Employee, current_user: User) -> None:
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave application not found")
    is_owner = employee.user_id == current_user.id
    is_hr = current_user.role.value in HR_WRITE_ROLES
    current_employee = _current_employee_or_none(db, current_user)
    is_manager_of = current_employee is not None and employee.reporting_manager_id == current_employee.id
    if not (is_owner or is_hr or is_manager_of):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _balance_remaining(balance: LeaveBalance) -> float:
    return balance.total_allocated + balance.carried_forward - balance.used - balance.encashed - balance.lapsed


def _to_balance_response(balance: LeaveBalance, leave_type_name: str) -> LeaveBalanceResponse:
    return LeaveBalanceResponse(
        id=balance.id,
        employee_id=balance.employee_id,
        leave_type_id=balance.leave_type_id,
        leave_type_name=leave_type_name,
        year=balance.year,
        total_allocated=balance.total_allocated,
        used=balance.used,
        carried_forward=balance.carried_forward,
        encashed=balance.encashed,
        lapsed=balance.lapsed,
        remaining=_balance_remaining(balance),
    )


def _to_application_response(db: Session, application: LeaveApplication) -> LeaveApplicationResponse:
    employee = db.get(Employee, application.employee_id)
    employee_user = db.get(User, employee.user_id)
    leave_type = db.get(LeaveType, application.leave_type_id)
    return LeaveApplicationResponse(
        id=application.id,
        employee_id=employee.id,
        employee_name=employee_user.full_name,
        employee_code=employee.employee_code,
        leave_type_id=leave_type.id,
        leave_type_name=leave_type.name,
        from_date=application.from_date,
        to_date=application.to_date,
        days=application.days,
        reason=application.reason,
        has_attachment=bool(application.attachment_path),
        status=application.status,
        applied_at=application.applied_at,
        manager_action_by=application.manager_action_by,
        manager_action_at=application.manager_action_at,
        hr_action_by=application.hr_action_by,
        hr_action_at=application.hr_action_at,
        rejection_reason=application.rejection_reason,
    )


def _to_application_detail(db: Session, application: LeaveApplication) -> LeaveApplicationDetail:
    base = _to_application_response(db, application)
    history_rows = list(
        db.scalars(
            select(LeaveApprovalHistory)
            .where(LeaveApprovalHistory.leave_application_id == application.id)
            .order_by(LeaveApprovalHistory.action_at)
        )
    )
    history = []
    for row in history_rows:
        actor_name = None
        if row.action_by:
            actor = db.get(User, row.action_by)
            actor_name = actor.full_name if actor else None
        history.append(
            LeaveApprovalHistoryResponse(
                id=row.id, action_by_name=actor_name, action=row.action, action_at=row.action_at, comments=row.comments
            )
        )
    return LeaveApplicationDetail(**base.model_dump(), history=history)


def _add_history(db: Session, application_id: int, action_by: int | None, action: LeaveApprovalAction, comments: str | None) -> None:
    db.add(LeaveApprovalHistory(leave_application_id=application_id, action_by=action_by, action=action, comments=comments))


# ---- Leave types ----

@router.get("/types", response_model=list[LeaveTypeResponse])
def list_leave_types(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[LeaveType]:
    return list(
        db.scalars(
            select(LeaveType).where(LeaveType.company_id == current_user.company_id, LeaveType.deleted_at.is_(None))
        )
    )


@router.post("/types", response_model=LeaveTypeResponse, status_code=status.HTTP_201_CREATED)
def create_leave_type(
    payload: LeaveTypeCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> LeaveType:
    leave_type = LeaveType(company_id=current_user.company_id, **payload.model_dump())
    db.add(leave_type)
    db.commit()
    db.refresh(leave_type)
    log_audit(
        db, user_id=current_user.id, action="leave_type_created", entity_type="leave_type",
        entity_id=leave_type.id, ip_address=get_client_ip(request),
    )
    return leave_type


@router.put("/types/{leave_type_id}", response_model=LeaveTypeResponse)
def update_leave_type(
    leave_type_id: int,
    payload: LeaveTypeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> LeaveType:
    leave_type = _get_leave_type_or_404(db, leave_type_id, current_user.company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(leave_type, field, value)
    db.commit()
    db.refresh(leave_type)
    return leave_type


@router.delete("/types/{leave_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_leave_type(
    leave_type_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> None:
    leave_type = _get_leave_type_or_404(db, leave_type_id, current_user.company_id)
    leave_type.deleted_at = utcnow()
    db.commit()


# ---- Balances ----

@router.get("/balances/me", response_model=list[LeaveBalanceResponse])
def my_balances(
    year: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[LeaveBalanceResponse]:
    employee = _get_own_employee_or_404(db, current_user)
    target_year = year or date.today().year
    rows = db.execute(
        select(LeaveBalance, LeaveType)
        .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
        .where(LeaveBalance.employee_id == employee.id, LeaveBalance.year == target_year)
    ).all()
    return [_to_balance_response(balance, leave_type.name) for balance, leave_type in rows]


@router.get("/balances", response_model=list[CompanyLeaveBalanceResponse])
def company_balances(
    year: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> list[CompanyLeaveBalanceResponse]:
    target_year = year or date.today().year
    rows = db.execute(
        select(LeaveBalance, LeaveType, Employee, User)
        .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
        .join(Employee, Employee.id == LeaveBalance.employee_id)
        .join(User, User.id == Employee.user_id)
        .where(
            Employee.company_id == current_user.company_id,
            Employee.deleted_at.is_(None),
            LeaveBalance.year == target_year,
        )
        .order_by(User.full_name, LeaveType.name)
    ).all()
    return [
        CompanyLeaveBalanceResponse(
            **_to_balance_response(balance, leave_type.name).model_dump(),
            employee_name=employee_user.full_name,
            employee_code=employee.employee_code,
        )
        for balance, leave_type, employee, employee_user in rows
    ]


@router.get("/balances/{employee_id}", response_model=list[LeaveBalanceResponse])
def employee_balances(
    employee_id: int,
    year: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> list[LeaveBalanceResponse]:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    target_year = year or date.today().year
    rows = db.execute(
        select(LeaveBalance, LeaveType)
        .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
        .where(LeaveBalance.employee_id == employee.id, LeaveBalance.year == target_year)
    ).all()
    return [_to_balance_response(balance, leave_type.name) for balance, leave_type in rows]


@router.post("/balances/allocate", response_model=AllocateBalancesResponse)
def allocate_balances(
    payload: AllocateBalancesRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> AllocateBalancesResponse:
    leave_type = _get_leave_type_or_404(db, payload.leave_type_id, current_user.company_id)
    employees = list(
        db.scalars(
            select(Employee).where(Employee.company_id == current_user.company_id, Employee.deleted_at.is_(None))
        )
    )

    created = 0
    for employee in employees:
        existing = db.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee.id,
                LeaveBalance.leave_type_id == leave_type.id,
                LeaveBalance.year == payload.year,
            )
        )
        if existing is not None:
            continue
        db.add(
            LeaveBalance(
                employee_id=employee.id, leave_type_id=leave_type.id, year=payload.year, total_allocated=payload.total_days
            )
        )
        created += 1
    db.commit()

    log_audit(
        db, user_id=current_user.id, action="leave_balances_allocated", entity_type="leave_type",
        entity_id=leave_type.id, ip_address=get_client_ip(request),
    )
    return AllocateBalancesResponse(created=created, skipped=len(employees) - created)


@router.post("/balances/{employee_id}/adjust", response_model=LeaveBalanceResponse)
def adjust_balance(
    employee_id: int,
    payload: AdjustBalanceRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> LeaveBalanceResponse:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    leave_type = _get_leave_type_or_404(db, payload.leave_type_id, current_user.company_id)

    balance = db.scalar(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee.id,
            LeaveBalance.leave_type_id == leave_type.id,
            LeaveBalance.year == payload.year,
        )
    )
    if balance is None:
        balance = LeaveBalance(employee_id=employee.id, leave_type_id=leave_type.id, year=payload.year)
        db.add(balance)

    updates = payload.model_dump(exclude_unset=True, exclude={"leave_type_id", "year"})
    for field, value in updates.items():
        if value is not None:
            setattr(balance, field, value)

    db.commit()
    db.refresh(balance)

    log_audit(
        db, user_id=current_user.id, action="leave_balance_adjusted", entity_type="leave_balance",
        entity_id=balance.id, ip_address=get_client_ip(request),
    )
    return _to_balance_response(balance, leave_type.name)


# ---- Applications ----

@router.post("/applications", response_model=LeaveApplicationDetail, status_code=status.HTTP_201_CREATED)
def apply_for_leave(
    request: Request,
    leave_type_id: int = Form(...),
    from_date: date = Form(...),
    to_date: date = Form(...),
    reason: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LeaveApplicationDetail:
    employee = _get_own_employee_or_404(db, current_user)
    leave_type = _get_leave_type_or_404(db, leave_type_id, current_user.company_id)

    if to_date < from_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="to_date must be on or after from_date")
    days = (to_date - from_date).days + 1

    if not leave_type.is_unpaid:
        balance = db.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee.id,
                LeaveBalance.leave_type_id == leave_type.id,
                LeaveBalance.year == from_date.year,
            )
        )
        available = _balance_remaining(balance) if balance else 0.0
        if days > available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient leave balance: {available} day(s) remaining for {leave_type.name}",
            )

    attachment_path = None
    if file is not None and file.filename:
        saved = save_leave_attachment(employee.company_id, employee.id, file)
        attachment_path = saved.file_path

    manager = db.get(Employee, employee.reporting_manager_id) if employee.reporting_manager_id else None
    manager_user = db.get(User, manager.user_id) if manager else None
    manager_active = manager is not None and manager.deleted_at is None and manager_user is not None and manager_user.is_active
    initial_status = LeaveApplicationStatus.PENDING_MANAGER if manager_active else LeaveApplicationStatus.PENDING_HR

    application = LeaveApplication(
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        from_date=from_date,
        to_date=to_date,
        days=days,
        reason=reason,
        attachment_path=attachment_path,
        status=initial_status,
    )
    db.add(application)
    db.flush()
    _add_history(db, application.id, current_user.id, LeaveApprovalAction.SUBMITTED, reason)
    db.commit()
    db.refresh(application)

    log_audit(
        db, user_id=current_user.id, action="leave_applied", entity_type="leave_application",
        entity_id=application.id, ip_address=get_client_ip(request),
    )

    if manager_active:
        send_email(
            to=manager_user.email,
            subject="Leave request awaiting your approval",
            body=f"{current_user.full_name} applied for {days} day(s) of {leave_type.name} leave ({from_date} to {to_date}).",
        )
        notify(
            db, user_id=manager_user.id, category=NotificationCategory.LEAVE,
            title="Leave request awaiting your approval",
            body=f"{current_user.full_name} applied for {days} day(s) of {leave_type.name} leave.",
            link="/manager/team-leave",
        )
    else:
        hr_recipients = db.scalars(
            select(User).where(
                User.company_id == current_user.company_id,
                User.role.in_([UserRole(role) for role in HR_WRITE_ROLES]),
            )
        )
        for hr_user in hr_recipients:
            send_email(
                to=hr_user.email,
                subject="Leave request awaiting your approval",
                body=f"{current_user.full_name} applied for {days} day(s) of {leave_type.name} leave ({from_date} to {to_date}).",
            )
        notify_many(
            db, user_ids=hr_user_ids(db, current_user.company_id), category=NotificationCategory.LEAVE,
            title="Leave request awaiting HR approval",
            body=f"{current_user.full_name} applied for {days} day(s) of {leave_type.name} leave.",
            link="/hr/leave",
        )

    return _to_application_detail(db, application)


@router.get("/applications/me", response_model=list[LeaveApplicationResponse])
def my_applications(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[LeaveApplicationResponse]:
    employee = _get_own_employee_or_404(db, current_user)
    applications = list(
        db.scalars(
            select(LeaveApplication)
            .where(LeaveApplication.employee_id == employee.id, LeaveApplication.deleted_at.is_(None))
            .order_by(LeaveApplication.applied_at.desc())
        )
    )
    return [_to_application_response(db, a) for a in applications]


@router.get("/applications", response_model=list[LeaveApplicationResponse])
def list_applications(
    status_filter: LeaveApplicationStatus | None = None,
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> list[LeaveApplicationResponse]:
    query = (
        select(LeaveApplication)
        .join(Employee, Employee.id == LeaveApplication.employee_id)
        .where(Employee.company_id == current_user.company_id, LeaveApplication.deleted_at.is_(None))
    )
    if status_filter is not None:
        query = query.where(LeaveApplication.status == status_filter)
    if employee_id is not None:
        query = query.where(LeaveApplication.employee_id == employee_id)
    applications = list(db.scalars(query.order_by(LeaveApplication.applied_at.desc())))
    return [_to_application_response(db, a) for a in applications]


@router.get("/applications/team", response_model=list[LeaveApplicationResponse])
def team_applications(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[LeaveApplicationResponse]:
    manager_employee = _get_own_employee_or_404(db, current_user)
    applications = list(
        db.scalars(
            select(LeaveApplication)
            .join(Employee, Employee.id == LeaveApplication.employee_id)
            .where(Employee.reporting_manager_id == manager_employee.id, LeaveApplication.deleted_at.is_(None))
            .order_by(LeaveApplication.applied_at.desc())
        )
    )
    return [_to_application_response(db, a) for a in applications]


@router.get("/calendar", response_model=list[LeaveApplicationResponse])
def leave_calendar(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[LeaveApplicationResponse]:
    query = (
        select(LeaveApplication)
        .join(Employee, Employee.id == LeaveApplication.employee_id)
        .where(
            Employee.company_id == current_user.company_id,
            LeaveApplication.status == LeaveApplicationStatus.APPROVED,
            LeaveApplication.deleted_at.is_(None),
        )
    )

    if current_user.role.value not in HR_WRITE_ROLES:
        current_employee = _current_employee_or_none(db, current_user)
        if current_employee is None:
            return []
        is_manager = db.scalar(
            select(Employee.id).where(Employee.reporting_manager_id == current_employee.id, Employee.deleted_at.is_(None))
        )
        if is_manager is not None:
            query = query.where(Employee.reporting_manager_id == current_employee.id)
        else:
            query = query.where(LeaveApplication.employee_id == current_employee.id)

    applications = list(db.scalars(query.order_by(LeaveApplication.from_date)))
    return [_to_application_response(db, a) for a in applications]


@router.get("/applications/{application_id}", response_model=LeaveApplicationDetail)
def get_application(
    application_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> LeaveApplicationDetail:
    application = _get_application_or_404(db, application_id)
    employee = db.get(Employee, application.employee_id)
    _authorize_application_access(db, employee, current_user)
    return _to_application_detail(db, application)


@router.get("/applications/{application_id}/attachment")
def download_attachment(
    application_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> FileResponse:
    application = _get_application_or_404(db, application_id)
    employee = db.get(Employee, application.employee_id)
    _authorize_application_access(db, employee, current_user)
    if not application.attachment_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No attachment for this application")
    return FileResponse(application.attachment_path)


@router.post("/applications/{application_id}/manager-action", response_model=LeaveApplicationDetail)
def manager_action(
    application_id: int,
    payload: LeaveActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LeaveApplicationDetail:
    application = _get_application_or_404(db, application_id)
    employee = db.get(Employee, application.employee_id)
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave application not found")

    current_employee = _current_employee_or_none(db, current_user)
    is_manager_of = current_employee is not None and employee.reporting_manager_id == current_employee.id
    is_hr = current_user.role.value in HR_WRITE_ROLES
    if not (is_manager_of or is_hr):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the assigned reporting manager or HR can act at this stage"
        )

    if application.status != LeaveApplicationStatus.PENDING_MANAGER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This application is not awaiting manager approval")

    employee_user = db.get(User, employee.user_id)

    if payload.action == "approve":
        application.status = LeaveApplicationStatus.PENDING_HR
        history_action = LeaveApprovalAction.MANAGER_APPROVED
        email_subject = "Leave request approved by manager"
        email_body = "Your leave request has been approved by your manager and is now awaiting HR approval."
    else:
        application.status = LeaveApplicationStatus.REJECTED
        application.rejection_reason = payload.comments
        history_action = LeaveApprovalAction.MANAGER_REJECTED
        email_subject = "Leave request rejected"
        email_body = f"Your leave request has been rejected by your manager. Reason: {payload.comments or 'Not specified'}"

    application.manager_action_by = current_user.id
    application.manager_action_at = utcnow()
    _add_history(db, application.id, current_user.id, history_action, payload.comments)
    db.commit()
    db.refresh(application)

    log_audit(
        db, user_id=current_user.id, action=f"leave_{history_action.value}", entity_type="leave_application",
        entity_id=application.id, ip_address=get_client_ip(request),
    )
    send_email(to=employee_user.email, subject=email_subject, body=email_body)
    notify(
        db, user_id=employee_user.id, category=NotificationCategory.LEAVE,
        title=email_subject, body=email_body, link="/employee/leave",
    )
    if payload.action == "approve":
        notify_many(
            db, user_ids=hr_user_ids(db, current_user.company_id), category=NotificationCategory.LEAVE,
            title="Leave request awaiting HR approval",
            body=f"{employee_user.full_name}'s leave request was approved by their manager and now needs HR approval.",
            link="/hr/leave",
        )

    return _to_application_detail(db, application)


@router.post("/applications/{application_id}/hr-action", response_model=LeaveApplicationDetail)
def hr_action(
    application_id: int,
    payload: LeaveActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> LeaveApplicationDetail:
    application = _get_application_or_404(db, application_id)
    employee = db.get(Employee, application.employee_id)
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave application not found")

    if application.status != LeaveApplicationStatus.PENDING_HR:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This application is not awaiting HR approval")

    employee_user = db.get(User, employee.user_id)

    if payload.action == "approve":
        application.status = LeaveApplicationStatus.APPROVED
        history_action = LeaveApprovalAction.HR_APPROVED
        email_subject = "Leave request approved"
        email_body = "Your leave request has been approved. Enjoy your time off!"

        leave_type = db.get(LeaveType, application.leave_type_id)
        if not leave_type.is_unpaid:
            year = application.from_date.year
            balance = db.scalar(
                select(LeaveBalance).where(
                    LeaveBalance.employee_id == employee.id,
                    LeaveBalance.leave_type_id == leave_type.id,
                    LeaveBalance.year == year,
                )
            )
            if balance is None:
                balance = LeaveBalance(employee_id=employee.id, leave_type_id=leave_type.id, year=year)
                db.add(balance)
            balance.used += application.days
    else:
        application.status = LeaveApplicationStatus.REJECTED
        application.rejection_reason = payload.comments
        history_action = LeaveApprovalAction.HR_REJECTED
        email_subject = "Leave request rejected"
        email_body = f"Your leave request has been rejected by HR. Reason: {payload.comments or 'Not specified'}"

    application.hr_action_by = current_user.id
    application.hr_action_at = utcnow()
    _add_history(db, application.id, current_user.id, history_action, payload.comments)
    db.commit()
    db.refresh(application)

    log_audit(
        db, user_id=current_user.id, action=f"leave_{history_action.value}", entity_type="leave_application",
        entity_id=application.id, ip_address=get_client_ip(request),
    )
    send_email(to=employee_user.email, subject=email_subject, body=email_body)
    notify(
        db, user_id=employee_user.id, category=NotificationCategory.LEAVE,
        title=email_subject, body=email_body, link="/employee/leave",
    )

    return _to_application_detail(db, application)


@router.post("/applications/{application_id}/cancel", response_model=LeaveApplicationDetail)
def cancel_application(
    application_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LeaveApplicationDetail:
    application = _get_application_or_404(db, application_id)
    employee = _get_own_employee_or_404(db, current_user)
    if application.employee_id != employee.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only cancel your own leave applications")

    if application.status not in (LeaveApplicationStatus.PENDING_MANAGER, LeaveApplicationStatus.PENDING_HR):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only pending applications can be cancelled")

    application.status = LeaveApplicationStatus.CANCELLED
    _add_history(db, application.id, current_user.id, LeaveApprovalAction.CANCELLED, None)
    db.commit()
    db.refresh(application)

    log_audit(
        db, user_id=current_user.id, action="leave_cancelled", entity_type="leave_application",
        entity_id=application.id, ip_address=get_client_ip(request),
    )
    return _to_application_detail(db, application)
