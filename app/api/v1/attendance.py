from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES, get_client_ip, get_current_user, get_db, require_role
from app.core.audit import log_audit
from app.core.email import send_email
from app.models.attendance import (
    AttendanceLog,
    AttendanceRegularization,
    AttendanceStatus,
    EmployeeShift,
    RegularizationStatus,
    Shift,
)
from app.models.employee import Employee
from app.models.mixins import utcnow
from app.models.user import User
from app.schemas.attendance import (
    AssignShiftRequest,
    AttendanceLogResponse,
    AttendanceReportRow,
    ClockInRequest,
    ClockOutRequest,
    EmployeeShiftResponse,
    RegularizationActionRequest,
    RegularizationCreate,
    RegularizationResponse,
    ShiftCreate,
    ShiftResponse,
    ShiftUpdate,
    TodayStatusResponse,
)

router = APIRouter(prefix="/attendance", tags=["attendance"])


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


def _get_shift_or_404(db: Session, shift_id: int, company_id: int | None) -> Shift:
    shift = db.scalar(
        select(Shift).where(Shift.id == shift_id, Shift.company_id == company_id, Shift.deleted_at.is_(None))
    )
    if shift is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
    return shift


def _current_employee_or_none(db: Session, current_user: User) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))


def _authorize_employee_view(db: Session, employee: Employee, current_user: User) -> None:
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    is_owner = employee.user_id == current_user.id
    is_hr = current_user.role.value in HR_WRITE_ROLES
    current_employee = _current_employee_or_none(db, current_user)
    is_manager_of = current_employee is not None and employee.reporting_manager_id == current_employee.id
    if not (is_owner or is_hr or is_manager_of):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _get_current_shift(db: Session, employee_id: int, on_date: date) -> Shift | None:
    assignment = db.scalar(
        select(EmployeeShift)
        .where(
            EmployeeShift.employee_id == employee_id,
            EmployeeShift.effective_from <= on_date,
            or_(EmployeeShift.effective_to.is_(None), EmployeeShift.effective_to >= on_date),
        )
        .order_by(EmployeeShift.effective_from.desc())
    )
    if assignment is None:
        return None
    return db.get(Shift, assignment.shift_id)


def _to_log_response(db: Session, log: AttendanceLog) -> AttendanceLogResponse:
    employee = db.get(Employee, log.employee_id)
    employee_user = db.get(User, employee.user_id)
    return AttendanceLogResponse(
        id=log.id,
        employee_id=employee.id,
        employee_name=employee_user.full_name,
        employee_code=employee.employee_code,
        date=log.date,
        clock_in=log.clock_in,
        clock_out=log.clock_out,
        status=log.status,
        work_hours=log.work_hours,
    )


def _to_reg_response(db: Session, reg: AttendanceRegularization) -> RegularizationResponse:
    employee = db.get(Employee, reg.employee_id)
    employee_user = db.get(User, employee.user_id)
    return RegularizationResponse(
        id=reg.id,
        employee_id=employee.id,
        employee_name=employee_user.full_name,
        employee_code=employee.employee_code,
        date=reg.date,
        requested_clock_in=reg.requested_clock_in,
        requested_clock_out=reg.requested_clock_out,
        reason=reg.reason,
        status=reg.status,
        approved_by=reg.approved_by,
        approved_at=reg.approved_at,
    )


# ---- Shifts ----

@router.get("/shifts", response_model=list[ShiftResponse])
def list_shifts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[Shift]:
    return list(
        db.scalars(select(Shift).where(Shift.company_id == current_user.company_id, Shift.deleted_at.is_(None)))
    )


@router.post("/shifts", response_model=ShiftResponse, status_code=status.HTTP_201_CREATED)
def create_shift(
    payload: ShiftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> Shift:
    shift = Shift(company_id=current_user.company_id, **payload.model_dump())
    db.add(shift)
    db.commit()
    db.refresh(shift)
    log_audit(
        db, user_id=current_user.id, action="shift_created", entity_type="shift", entity_id=shift.id,
        ip_address=get_client_ip(request),
    )
    return shift


@router.put("/shifts/{shift_id}", response_model=ShiftResponse)
def update_shift(
    shift_id: int,
    payload: ShiftUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> Shift:
    shift = _get_shift_or_404(db, shift_id, current_user.company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shift, field, value)
    db.commit()
    db.refresh(shift)
    return shift


@router.delete("/shifts/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shift(
    shift_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> None:
    shift = _get_shift_or_404(db, shift_id, current_user.company_id)
    shift.deleted_at = utcnow()
    db.commit()


@router.post("/shifts/{shift_id}/assign", response_model=EmployeeShiftResponse)
def assign_shift(
    shift_id: int,
    payload: AssignShiftRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> EmployeeShiftResponse:
    shift = _get_shift_or_404(db, shift_id, current_user.company_id)
    employee = _get_employee_or_404(db, payload.employee_id, current_user.company_id)

    current_assignment = db.scalar(
        select(EmployeeShift).where(EmployeeShift.employee_id == employee.id, EmployeeShift.effective_to.is_(None))
    )
    if current_assignment is not None:
        current_assignment.effective_to = payload.effective_from

    new_assignment = EmployeeShift(
        employee_id=employee.id, shift_id=shift.id, effective_from=payload.effective_from, effective_to=None
    )
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)

    log_audit(
        db, user_id=current_user.id, action="shift_assigned", entity_type="employee_shift",
        entity_id=new_assignment.id, ip_address=get_client_ip(request),
    )
    return EmployeeShiftResponse(
        id=new_assignment.id, employee_id=employee.id, shift_id=shift.id, shift_name=shift.name,
        effective_from=new_assignment.effective_from, effective_to=new_assignment.effective_to,
    )


# ---- Clock in/out ----

@router.post("/clock-in", response_model=AttendanceLogResponse)
def clock_in(
    payload: ClockInRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AttendanceLogResponse:
    employee = _get_own_employee_or_404(db, current_user)
    today = date.today()

    log = db.scalar(select(AttendanceLog).where(AttendanceLog.employee_id == employee.id, AttendanceLog.date == today))
    if log is not None and log.clock_in is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already clocked in today")

    if log is None:
        log = AttendanceLog(employee_id=employee.id, date=today)
        db.add(log)

    log.clock_in = utcnow()
    log.clock_in_ip = get_client_ip(request)
    log.clock_in_lat = payload.latitude
    log.clock_in_lng = payload.longitude
    db.commit()
    db.refresh(log)

    log_audit(
        db, user_id=current_user.id, action="clocked_in", entity_type="attendance_log", entity_id=log.id,
        ip_address=get_client_ip(request),
    )
    return _to_log_response(db, log)


@router.post("/clock-out", response_model=AttendanceLogResponse)
def clock_out(
    payload: ClockOutRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AttendanceLogResponse:
    employee = _get_own_employee_or_404(db, current_user)
    today = date.today()

    log = db.scalar(select(AttendanceLog).where(AttendanceLog.employee_id == employee.id, AttendanceLog.date == today))
    if log is None or log.clock_in is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have not clocked in today")
    if log.clock_out is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already clocked out today")

    log.clock_out = utcnow()
    log.clock_out_ip = get_client_ip(request)
    log.clock_out_lat = payload.latitude
    log.clock_out_lng = payload.longitude

    work_hours = (log.clock_out - log.clock_in).total_seconds() / 3600
    log.work_hours = round(work_hours, 2)

    shift = _get_current_shift(db, employee.id, today)
    is_late = False
    if shift is not None:
        shift_start_dt = datetime.combine(today, shift.start_time)
        clock_in_dt = datetime.combine(today, log.clock_in.time())
        is_late = clock_in_dt > shift_start_dt + timedelta(minutes=shift.grace_period_minutes)

    if is_late:
        log.status = AttendanceStatus.LATE
    elif work_hours < 4:
        log.status = AttendanceStatus.HALF_DAY
    else:
        log.status = AttendanceStatus.PRESENT

    db.commit()
    db.refresh(log)

    log_audit(
        db, user_id=current_user.id, action="clocked_out", entity_type="attendance_log", entity_id=log.id,
        ip_address=get_client_ip(request),
    )
    return _to_log_response(db, log)


@router.get("/today/me", response_model=TodayStatusResponse)
def my_today_status(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> TodayStatusResponse:
    employee = _get_own_employee_or_404(db, current_user)
    today = date.today()
    log = db.scalar(select(AttendanceLog).where(AttendanceLog.employee_id == employee.id, AttendanceLog.date == today))
    if log is None:
        return TodayStatusResponse(clocked_in=False, clocked_out=False, clock_in=None, clock_out=None, status=None)
    return TodayStatusResponse(
        clocked_in=log.clock_in is not None, clocked_out=log.clock_out is not None,
        clock_in=log.clock_in, clock_out=log.clock_out, status=log.status,
    )


# ---- Timesheets & reports ----

@router.get("/me", response_model=list[AttendanceLogResponse])
def my_attendance(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AttendanceLogResponse]:
    employee = _get_own_employee_or_404(db, current_user)
    logs = list(
        db.scalars(
            select(AttendanceLog)
            .where(AttendanceLog.employee_id == employee.id, AttendanceLog.date >= from_date, AttendanceLog.date <= to_date)
            .order_by(AttendanceLog.date)
        )
    )
    return [_to_log_response(db, log) for log in logs]


@router.get("/employee/{employee_id}", response_model=list[AttendanceLogResponse])
def employee_attendance(
    employee_id: int,
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AttendanceLogResponse]:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    _authorize_employee_view(db, employee, current_user)
    logs = list(
        db.scalars(
            select(AttendanceLog)
            .where(AttendanceLog.employee_id == employee.id, AttendanceLog.date >= from_date, AttendanceLog.date <= to_date)
            .order_by(AttendanceLog.date)
        )
    )
    return [_to_log_response(db, log) for log in logs]


@router.get("/report", response_model=list[AttendanceReportRow])
def attendance_report(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> list[AttendanceReportRow]:
    query = (
        select(AttendanceLog)
        .join(Employee, Employee.id == AttendanceLog.employee_id)
        .where(Employee.company_id == current_user.company_id, AttendanceLog.date >= from_date, AttendanceLog.date <= to_date)
    )
    if employee_id is not None:
        query = query.where(AttendanceLog.employee_id == employee_id)

    logs = list(db.scalars(query))
    grouped: dict[int, list[AttendanceLog]] = {}
    for log in logs:
        grouped.setdefault(log.employee_id, []).append(log)

    rows = []
    for emp_id, emp_logs in grouped.items():
        employee = db.get(Employee, emp_id)
        employee_user = db.get(User, employee.user_id)
        rows.append(
            AttendanceReportRow(
                employee_id=emp_id,
                employee_name=employee_user.full_name,
                employee_code=employee.employee_code,
                present_days=sum(1 for log in emp_logs if log.status == AttendanceStatus.PRESENT),
                late_days=sum(1 for log in emp_logs if log.status == AttendanceStatus.LATE),
                half_days=sum(1 for log in emp_logs if log.status == AttendanceStatus.HALF_DAY),
                total_hours=round(sum(log.work_hours or 0 for log in emp_logs), 2),
            )
        )
    return rows


# ---- Regularizations ----

@router.post("/regularizations", response_model=RegularizationResponse, status_code=status.HTTP_201_CREATED)
def request_regularization(
    payload: RegularizationCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RegularizationResponse:
    employee = _get_own_employee_or_404(db, current_user)
    reg = AttendanceRegularization(
        employee_id=employee.id,
        date=payload.date,
        requested_clock_in=payload.requested_clock_in,
        requested_clock_out=payload.requested_clock_out,
        reason=payload.reason,
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)

    log_audit(
        db, user_id=current_user.id, action="regularization_requested", entity_type="attendance_regularization",
        entity_id=reg.id, ip_address=get_client_ip(request),
    )
    return _to_reg_response(db, reg)


@router.get("/regularizations/me", response_model=list[RegularizationResponse])
def my_regularizations(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[RegularizationResponse]:
    employee = _get_own_employee_or_404(db, current_user)
    regs = list(
        db.scalars(
            select(AttendanceRegularization)
            .where(AttendanceRegularization.employee_id == employee.id)
            .order_by(AttendanceRegularization.date.desc())
        )
    )
    return [_to_reg_response(db, reg) for reg in regs]


@router.get("/regularizations", response_model=list[RegularizationResponse])
def list_regularizations(
    status_filter: RegularizationStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RegularizationResponse]:
    is_hr = current_user.role.value in HR_WRITE_ROLES
    query = (
        select(AttendanceRegularization)
        .join(Employee, Employee.id == AttendanceRegularization.employee_id)
        .where(Employee.company_id == current_user.company_id)
    )
    if not is_hr:
        current_employee = _current_employee_or_none(db, current_user)
        if current_employee is None:
            return []
        query = query.where(Employee.reporting_manager_id == current_employee.id)
    if status_filter is not None:
        query = query.where(AttendanceRegularization.status == status_filter)

    regs = list(db.scalars(query.order_by(AttendanceRegularization.date.desc())))
    return [_to_reg_response(db, reg) for reg in regs]


def _get_regularization_or_404(db: Session, regularization_id: int) -> AttendanceRegularization:
    reg = db.get(AttendanceRegularization, regularization_id)
    if reg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regularization request not found")
    return reg


@router.post("/regularizations/{regularization_id}/action", response_model=RegularizationResponse)
def act_on_regularization(
    regularization_id: int,
    payload: RegularizationActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RegularizationResponse:
    reg = _get_regularization_or_404(db, regularization_id)
    employee = db.get(Employee, reg.employee_id)
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regularization request not found")

    is_hr = current_user.role.value in HR_WRITE_ROLES
    current_employee = _current_employee_or_none(db, current_user)
    is_manager_of = current_employee is not None and employee.reporting_manager_id == current_employee.id
    if not (is_hr or is_manager_of):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    if reg.status != RegularizationStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This request has already been actioned")

    if payload.action == "approve":
        reg.status = RegularizationStatus.APPROVED
        log = db.scalar(
            select(AttendanceLog).where(AttendanceLog.employee_id == reg.employee_id, AttendanceLog.date == reg.date)
        )
        if log is None:
            log = AttendanceLog(employee_id=reg.employee_id, date=reg.date)
            db.add(log)
        if reg.requested_clock_in is not None:
            log.clock_in = reg.requested_clock_in
        if reg.requested_clock_out is not None:
            log.clock_out = reg.requested_clock_out
        if log.clock_in is not None and log.clock_out is not None:
            log.work_hours = round((log.clock_out - log.clock_in).total_seconds() / 3600, 2)
            log.status = AttendanceStatus.PRESENT
        db.flush()
        log.regularization_id = reg.id
    else:
        reg.status = RegularizationStatus.REJECTED

    reg.approved_by = current_user.id
    reg.approved_at = utcnow()
    db.commit()
    db.refresh(reg)

    log_audit(
        db, user_id=current_user.id, action=f"regularization_{reg.status.value}", entity_type="attendance_regularization",
        entity_id=reg.id, ip_address=get_client_ip(request),
    )
    employee_user = db.get(User, employee.user_id)
    send_email(
        to=employee_user.email,
        subject=f"Attendance regularization {reg.status.value}",
        body=f"Your attendance correction request for {reg.date} has been {reg.status.value}.",
    )
    return _to_reg_response(db, reg)
