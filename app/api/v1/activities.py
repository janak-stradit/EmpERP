from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
import io
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_role, HR_WRITE_ROLES, ADMIN_ROLES
from app.core.audit import log_audit
from app.api.deps import get_client_ip
from app.models.employee import Employee
from app.models.activity import ActivityCategory, ActivityLog, DailyActivityStatus
from app.models.user import User
from app.schemas.activity import ActivityCategoryResponse, ActivityLogCreate, ActivityLogUpdate, ActivityLogResponse, EmployeeSummary, DailyStatusUpdate, DailyStatusResponse

router = APIRouter(prefix="/activities", tags=["activities"])

@router.get("/categories", response_model=list[ActivityCategoryResponse])
def get_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> list[ActivityCategory]:
    categories = db.scalars(
        select(ActivityCategory).where(
            ActivityCategory.company_id == current_user.company_id,
            ActivityCategory.deleted_at.is_(None)
        )
    ).all()
    
    # Auto-seed basic categories if none exist for easy testing
    if not categories:
        seed_names = ["Deep Work / Focus", "Meetings / Calls", "Email / Comms", "Planning / Admin", "Collaboration", "Learning / Training", "Break"]
        for name in seed_names:
            cat = ActivityCategory(company_id=current_user.company_id, name=name)
            db.add(cat)
        db.commit()
        categories = db.scalars(
            select(ActivityCategory).where(
                ActivityCategory.company_id == current_user.company_id,
                ActivityCategory.deleted_at.is_(None)
            )
        ).all()
        
    return list(categories)


@router.post("/log", response_model=ActivityLogResponse, status_code=status.HTTP_201_CREATED)
def log_activity(
    payload: ActivityLogCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> ActivityLog:
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")

    category = db.scalar(select(ActivityCategory).where(ActivityCategory.id == payload.category_id, ActivityCategory.company_id == current_user.company_id))
    if category is None:
        raise HTTPException(status_code=400, detail="Invalid category")

    status_entry = db.scalar(
        select(DailyActivityStatus).where(
            DailyActivityStatus.employee_id == employee.id,
            DailyActivityStatus.log_date == payload.log_date
        )
    )
    if status_entry and status_entry.status in ["On Leave", "Holiday"]:
        raise HTTPException(status_code=400, detail=f"Cannot log activities on a day marked as {status_entry.status}")

    # Check if a log already exists for this exact time block
    existing_log = db.scalar(
        select(ActivityLog).where(
            ActivityLog.employee_id == employee.id,
            ActivityLog.log_date == payload.log_date,
            ActivityLog.time_block == payload.time_block
        )
    )
    
    if existing_log:
        # Update existing
        existing_log.category_id = payload.category_id
        existing_log.duration_minutes = payload.duration_minutes
        existing_log.is_overtime = payload.is_overtime
        existing_log.notes = payload.notes
        db.commit()
        db.refresh(existing_log)
        
        # Attach category for response
        existing_log.category = category
        return existing_log
    else:
        # Create new
        new_log = ActivityLog(
            employee_id=employee.id,
            category_id=payload.category_id,
            log_date=payload.log_date,
            time_block=payload.time_block,
            duration_minutes=payload.duration_minutes,
            is_overtime=payload.is_overtime,
            notes=payload.notes
        )
        db.add(new_log)
        db.commit()
        db.refresh(new_log)
        
        # Attach category for response
        new_log.category = category
        
        log_audit(
            db,
            user_id=current_user.id,
            action="activity_logged",
            entity_type="activity_log",
            entity_id=new_log.id,
            ip_address=get_client_ip(request),
        )
        return new_log

@router.delete("/log/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")

    log_entry = db.scalar(select(ActivityLog).where(ActivityLog.id == log_id, ActivityLog.employee_id == employee.id))
    if not log_entry:
        raise HTTPException(status_code=404, detail="Activity log not found")

    db.delete(log_entry)
    db.commit()

    log_audit(
        db,
        user_id=current_user.id,
        action="activity_deleted",
        entity_type="activity_log",
        entity_id=log_id,
        ip_address=get_client_ip(request),
    )

@router.put("/log/{log_id}", response_model=ActivityLogResponse)
def update_activity(
    log_id: int,
    payload: ActivityLogUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")

    log_entry = db.scalar(select(ActivityLog).where(ActivityLog.id == log_id, ActivityLog.employee_id == employee.id))
    if not log_entry:
        raise HTTPException(status_code=404, detail="Activity log not found")

    category = db.scalar(select(ActivityCategory).where(ActivityCategory.id == payload.category_id, ActivityCategory.company_id == current_user.company_id))
    if category is None:
        raise HTTPException(status_code=400, detail="Invalid category")

    status_entry = db.scalar(
        select(DailyActivityStatus).where(
            DailyActivityStatus.employee_id == employee.id,
            DailyActivityStatus.log_date == payload.log_date
        )
    )
    if status_entry and status_entry.status in ["On Leave", "Holiday"]:
        raise HTTPException(status_code=400, detail=f"Cannot log activities on a day marked as {status_entry.status}")

    log_entry.category_id = payload.category_id
    log_entry.log_date = payload.log_date
    log_entry.time_block = payload.time_block
    log_entry.duration_minutes = payload.duration_minutes
    log_entry.is_overtime = payload.is_overtime
    log_entry.notes = payload.notes

    db.commit()
    db.refresh(log_entry)
    log_entry.category = category

    log_audit(
        db,
        user_id=current_user.id,
        action="activity_updated",
        entity_type="activity_log",
        entity_id=log_entry.id,
        ip_address=get_client_ip(request),
    )
    return log_entry


@router.get("/me", response_model=list[ActivityLogResponse])
def my_activities(
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        return []

    query = select(ActivityLog, ActivityCategory).join(ActivityCategory).where(ActivityLog.employee_id == employee.id)
    
    if start_date:
        query = query.where(ActivityLog.log_date >= start_date)
    if end_date:
        query = query.where(ActivityLog.log_date <= end_date)
        
    query = query.order_by(ActivityLog.log_date, ActivityLog.time_block)
    
    results = db.execute(query).all()
    
    # Map for response
    response_logs = []
    for log, cat in results:
        log.category = cat
        response_logs.append(log)
    return response_logs


@router.get("/team-summary", response_model=list[EmployeeSummary])
def get_team_summary(
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    manager = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if manager is None:
        return []

    from app.models.team import TeamMapping
    mapped_employee_ids = db.scalars(
        select(TeamMapping.employee_id).where(TeamMapping.manager_id == manager.id)
    ).all()
    
    if not mapped_employee_ids:
        return []

    mapped_employees = db.execute(
        select(Employee.id, User.full_name)
        .join(User, Employee.user_id == User.id)
        .where(Employee.id.in_(mapped_employee_ids))
    ).all()

    summary_map = {}
    for emp_id, emp_name in mapped_employees:
        summary_map[emp_id] = {
            "employee_id": emp_id,
            "employee_name": emp_name,
            "total_regular_hours": 0.0,
            "total_overtime_hours": 0.0,
            "categories": {},
            "statuses": {}
        }

    logs = db.execute(
        select(ActivityLog, ActivityCategory, Employee.id)
        .join(ActivityCategory, ActivityLog.category_id == ActivityCategory.id)
        .join(Employee, ActivityLog.employee_id == Employee.id)
        .where(
            ActivityLog.employee_id.in_(mapped_employee_ids),
            ActivityLog.log_date >= start_date,
            ActivityLog.log_date <= end_date
        )
    ).all()

    for log, cat, emp_id in logs:
        if emp_id not in summary_map:
            continue
            
        hours = log.duration_minutes / 60.0
        if log.is_overtime:
            summary_map[emp_id]["total_overtime_hours"] += hours
        else:
            summary_map[emp_id]["total_regular_hours"] += hours
            
        if cat.name not in summary_map[emp_id]["categories"]:
            summary_map[emp_id]["categories"][cat.name] = 0.0
        summary_map[emp_id]["categories"][cat.name] += hours

    statuses = db.execute(
        select(DailyActivityStatus.employee_id, DailyActivityStatus.status)
        .where(
            DailyActivityStatus.employee_id.in_(mapped_employee_ids),
            DailyActivityStatus.log_date >= start_date,
            DailyActivityStatus.log_date <= end_date
        )
    ).all()

    for emp_id, status in statuses:
        if emp_id in summary_map:
            if status not in summary_map[emp_id]["statuses"]:
                summary_map[emp_id]["statuses"][status] = 0
            summary_map[emp_id]["statuses"][status] += 1

    response = []
    for emp_data in summary_map.values():
        from app.schemas.activity import CategoryHours
        cats = [CategoryHours(category_name=k, hours=round(v, 2)) for k, v in emp_data["categories"].items()]
        response.append(
            EmployeeSummary(
                employee_id=emp_data["employee_id"],
                employee_name=emp_data["employee_name"],
                total_regular_hours=round(emp_data["total_regular_hours"], 2),
                total_overtime_hours=round(emp_data["total_overtime_hours"], 2),
                categories=cats,
                statuses=emp_data["statuses"]
            )
        )
        
    return response

@router.get("/company-summary", response_model=list[EmployeeSummary])
def get_company_summary(
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*ADMIN_ROLES))
):
    company_employees = db.execute(
        select(Employee.id, User.full_name)
        .join(User, Employee.user_id == User.id)
        .where(Employee.company_id == current_user.company_id)
    ).all()
    
    summary_map = {}
    for emp_id, emp_name in company_employees:
        summary_map[emp_id] = {
            "employee_id": emp_id,
            "employee_name": emp_name,
            "total_regular_hours": 0.0,
            "total_overtime_hours": 0.0,
            "categories": {},
            "statuses": {}
        }

    logs = db.execute(
        select(ActivityLog, ActivityCategory, Employee.id)
        .join(ActivityCategory, ActivityLog.category_id == ActivityCategory.id)
        .join(Employee, ActivityLog.employee_id == Employee.id)
        .where(
            Employee.company_id == current_user.company_id,
            ActivityLog.log_date >= start_date,
            ActivityLog.log_date <= end_date
        )
    ).all()

    for log, cat, emp_id in logs:
        if emp_id not in summary_map:
            continue
            
        hours = log.duration_minutes / 60.0
        if log.is_overtime:
            summary_map[emp_id]["total_overtime_hours"] += hours
        else:
            summary_map[emp_id]["total_regular_hours"] += hours
            
        if cat.name not in summary_map[emp_id]["categories"]:
            summary_map[emp_id]["categories"][cat.name] = 0.0
        summary_map[emp_id]["categories"][cat.name] += hours

    statuses = db.execute(
        select(DailyActivityStatus.employee_id, DailyActivityStatus.status)
        .join(Employee, DailyActivityStatus.employee_id == Employee.id)
        .where(
            Employee.company_id == current_user.company_id,
            DailyActivityStatus.log_date >= start_date,
            DailyActivityStatus.log_date <= end_date
        )
    ).all()

    for emp_id, status in statuses:
        if emp_id in summary_map:
            if status not in summary_map[emp_id]["statuses"]:
                summary_map[emp_id]["statuses"][status] = 0
            summary_map[emp_id]["statuses"][status] += 1

    response = []
    for emp_data in summary_map.values():
        from app.schemas.activity import CategoryHours
        cats = [CategoryHours(category_name=k, hours=round(v, 2)) for k, v in emp_data["categories"].items()]
        response.append(
            EmployeeSummary(
                employee_id=emp_data["employee_id"],
                employee_name=emp_data["employee_name"],
                total_regular_hours=round(emp_data["total_regular_hours"], 2),
                total_overtime_hours=round(emp_data["total_overtime_hours"], 2),
                categories=cats,
                statuses=emp_data["statuses"]
            )
        )
        
    return response

@router.get("/export/{employee_id}")
def export_employee_activities(
    employee_id: int,
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*ADMIN_ROLES))
):
    employee = db.scalar(select(Employee).where(Employee.id == employee_id, Employee.company_id == current_user.company_id))
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
        
    emp_user = db.get(User, employee.user_id)
    
    logs = db.execute(
        select(ActivityLog, ActivityCategory)
        .join(ActivityCategory)
        .where(
            ActivityLog.employee_id == employee_id,
            ActivityLog.log_date >= start_date,
            ActivityLog.log_date <= end_date
        )
        .order_by(ActivityLog.log_date, ActivityLog.time_block)
    ).all()
    
    statuses = db.execute(
        select(DailyActivityStatus.log_date, DailyActivityStatus.status)
        .where(
            DailyActivityStatus.employee_id == employee_id,
            DailyActivityStatus.log_date >= start_date,
            DailyActivityStatus.log_date <= end_date
        )
    ).all()
    status_map = {row.log_date: row.status for row in statuses}
    
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl is not installed")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Activities"
    
    headers = ["Date", "Status", "Time Block", "Category", "Duration (Mins)", "Overtime?", "Notes"]
    ws.append(headers)
    
    logs_by_date = {}
    for log, cat in logs:
        if log.log_date not in logs_by_date:
            logs_by_date[log.log_date] = []
        logs_by_date[log.log_date].append((log, cat))
        
    from datetime import timedelta
    current_date = start_date
    while current_date <= end_date:
        daily_status = status_map.get(current_date, "Working")
        day_logs = logs_by_date.get(current_date, [])
        
        if not day_logs:
            ws.append([
                current_date.isoformat(),
                daily_status,
                "-",
                "-",
                0,
                "No",
                ""
            ])
        else:
            for log, cat in day_logs:
                ws.append([
                    log.log_date.isoformat(),
                    daily_status,
                    log.time_block,
                    cat.name,
                    log.duration_minutes,
                    "Yes" if log.is_overtime else "No",
                    log.notes or ""
                ])
        current_date += timedelta(days=1)
        
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    
    filename = f"Activities_{emp_user.full_name.replace(' ', '_')}_{start_date}_to_{end_date}.xlsx"
    return StreamingResponse(
        stream, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/status/{log_date}", response_model=DailyStatusResponse)
def get_daily_status(
    log_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")

    status_entry = db.scalar(
        select(DailyActivityStatus).where(
            DailyActivityStatus.employee_id == employee.id,
            DailyActivityStatus.log_date == log_date
        )
    )

    if not status_entry:
        return DailyActivityStatus(
            id=0,
            employee_id=employee.id,
            log_date=log_date,
            status="Working",
            notes=None
        )

    return status_entry


@router.put("/status/{log_date}", response_model=DailyStatusResponse)
def update_daily_status(
    log_date: date,
    payload: DailyStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")

    status_entry = db.scalar(
        select(DailyActivityStatus).where(
            DailyActivityStatus.employee_id == employee.id,
            DailyActivityStatus.log_date == log_date
        )
    )

    if status_entry:
        status_entry.status = payload.status
        status_entry.notes = payload.notes
    else:
        status_entry = DailyActivityStatus(
            employee_id=employee.id,
            log_date=log_date,
            status=payload.status,
            notes=payload.notes
        )
        db.add(status_entry)

    db.commit()
    db.refresh(status_entry)
    
    return status_entry
