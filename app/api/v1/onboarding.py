from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES, get_client_ip, get_current_user, get_db, require_role
from app.core.audit import log_audit
from app.core.email import send_email
from app.core.notifications import hr_user_ids, notify, notify_many
from app.models.employee import Employee
from app.models.mixins import utcnow
from app.models.notification import NotificationCategory
from app.models.onboarding import (
    EmployeeOnboarding,
    EmployeeOnboardingTask,
    OnboardingStatus,
    OnboardingTask,
    OnboardingTaskStatus,
    OnboardingTemplate,
)
from app.models.user import User, UserRole
from app.schemas.onboarding import (
    AssignOnboardingRequest,
    EmployeeOnboardingResponse,
    EmployeeOnboardingTaskResponse,
    OnboardingTaskCreate,
    OnboardingTaskResponse,
    OnboardingTaskUpdate,
    OnboardingTemplateCreate,
    OnboardingTemplateDetail,
    OnboardingTemplateResponse,
    OnboardingTemplateUpdate,
    UpdateOnboardingTaskStatusRequest,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ---- Templates ----

def _get_template_or_404(db: Session, template_id: int, company_id: int | None) -> OnboardingTemplate:
    template = db.scalar(
        select(OnboardingTemplate).where(
            OnboardingTemplate.id == template_id,
            OnboardingTemplate.company_id == company_id,
            OnboardingTemplate.deleted_at.is_(None),
        )
    )
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding template not found")
    return template


def _template_detail(db: Session, template: OnboardingTemplate) -> OnboardingTemplateDetail:
    tasks = list(db.scalars(select(OnboardingTask).where(OnboardingTask.template_id == template.id)))
    return OnboardingTemplateDetail(
        id=template.id,
        company_id=template.company_id,
        name=template.name,
        description=template.description,
        tasks=[OnboardingTaskResponse.model_validate(t) for t in tasks],
    )


@router.get("/templates", response_model=list[OnboardingTemplateResponse])
def list_templates(
    db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> list[OnboardingTemplate]:
    return list(
        db.scalars(
            select(OnboardingTemplate).where(
                OnboardingTemplate.company_id == current_user.company_id,
                OnboardingTemplate.deleted_at.is_(None),
            )
        )
    )


@router.post("/templates", response_model=OnboardingTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: OnboardingTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> OnboardingTemplate:
    template = OnboardingTemplate(
        company_id=current_user.company_id, name=payload.name, description=payload.description
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    log_audit(
        db,
        user_id=current_user.id,
        action="onboarding_template_created",
        entity_type="onboarding_template",
        entity_id=template.id,
        ip_address=get_client_ip(request),
    )
    return template


@router.get("/templates/{template_id}", response_model=OnboardingTemplateDetail)
def get_template(
    template_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> OnboardingTemplateDetail:
    template = _get_template_or_404(db, template_id, current_user.company_id)
    return _template_detail(db, template)


@router.put("/templates/{template_id}", response_model=OnboardingTemplateResponse)
def update_template(
    template_id: int,
    payload: OnboardingTemplateUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> OnboardingTemplate:
    template = _get_template_or_404(db, template_id, current_user.company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    log_audit(
        db,
        user_id=current_user.id,
        action="onboarding_template_updated",
        entity_type="onboarding_template",
        entity_id=template.id,
        ip_address=get_client_ip(request),
    )
    return template


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> None:
    template = _get_template_or_404(db, template_id, current_user.company_id)
    template.deleted_at = utcnow()
    db.commit()
    log_audit(
        db,
        user_id=current_user.id,
        action="onboarding_template_deleted",
        entity_type="onboarding_template",
        entity_id=template.id,
        ip_address=get_client_ip(request),
    )


# ---- Tasks (within a template) ----

@router.post(
    "/templates/{template_id}/tasks", response_model=OnboardingTaskResponse, status_code=status.HTTP_201_CREATED
)
def add_task(
    template_id: int,
    payload: OnboardingTaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> OnboardingTask:
    _get_template_or_404(db, template_id, current_user.company_id)
    task = OnboardingTask(template_id=template_id, **payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    log_audit(
        db,
        user_id=current_user.id,
        action="onboarding_task_created",
        entity_type="onboarding_task",
        entity_id=task.id,
        ip_address=get_client_ip(request),
    )
    return task


@router.put("/templates/{template_id}/tasks/{task_id}", response_model=OnboardingTaskResponse)
def update_task(
    template_id: int,
    task_id: int,
    payload: OnboardingTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> OnboardingTask:
    _get_template_or_404(db, template_id, current_user.company_id)
    task = db.scalar(select(OnboardingTask).where(OnboardingTask.id == task_id, OnboardingTask.template_id == template_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding task not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/templates/{template_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    template_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> None:
    _get_template_or_404(db, template_id, current_user.company_id)
    task = db.scalar(select(OnboardingTask).where(OnboardingTask.id == task_id, OnboardingTask.template_id == template_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding task not found")
    db.delete(task)
    db.commit()


# ---- Assignment & progress ----

def _to_response(db: Session, onboarding: EmployeeOnboarding) -> EmployeeOnboardingResponse:
    rows = db.execute(
        select(EmployeeOnboardingTask, OnboardingTask)
        .join(OnboardingTask, OnboardingTask.id == EmployeeOnboardingTask.task_id)
        .where(EmployeeOnboardingTask.onboarding_id == onboarding.id)
    ).all()
    tasks = [
        EmployeeOnboardingTaskResponse(
            id=eot.id,
            task_id=eot.task_id,
            title=ot.title,
            status=eot.status,
            assigned_to_user_id=eot.assigned_to_user_id,
            due_date=eot.due_date,
            completed_at=eot.completed_at,
            notes=eot.notes,
        )
        for eot, ot in rows
    ]
    completed = sum(1 for t in tasks if t.status == OnboardingTaskStatus.COMPLETED)
    progress = (completed / len(tasks) * 100) if tasks else 0.0
    return EmployeeOnboardingResponse(
        id=onboarding.id,
        employee_id=onboarding.employee_id,
        template_id=onboarding.template_id,
        status=onboarding.status,
        started_at=onboarding.started_at,
        completed_at=onboarding.completed_at,
        progress_percent=round(progress, 1),
        tasks=tasks,
    )


@router.post("/assign", response_model=EmployeeOnboardingResponse, status_code=status.HTTP_201_CREATED)
def assign_onboarding(
    payload: AssignOnboardingRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> EmployeeOnboardingResponse:
    employee = db.scalar(
        select(Employee).where(
            Employee.id == payload.employee_id,
            Employee.company_id == current_user.company_id,
            Employee.deleted_at.is_(None),
        )
    )
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    template = _get_template_or_404(db, payload.template_id, current_user.company_id)
    template_tasks = list(db.scalars(select(OnboardingTask).where(OnboardingTask.template_id == template.id)))
    if not template_tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template has no tasks to assign")

    now = utcnow()
    onboarding = EmployeeOnboarding(
        employee_id=employee.id,
        template_id=template.id,
        status=OnboardingStatus.IN_PROGRESS,
        started_at=now,
    )
    db.add(onboarding)
    db.flush()

    for task in template_tasks:
        assigned_to_user_id = employee.user_id if task.assigned_to_role == UserRole.EMPLOYEE else None
        db.add(
            EmployeeOnboardingTask(
                onboarding_id=onboarding.id,
                task_id=task.id,
                assigned_to_user_id=assigned_to_user_id,
                due_date=(now + timedelta(days=task.due_days)).date(),
            )
        )
    db.commit()
    db.refresh(onboarding)

    log_audit(
        db,
        user_id=current_user.id,
        action="onboarding_assigned",
        entity_type="employee_onboarding",
        entity_id=onboarding.id,
        ip_address=get_client_ip(request),
    )
    employee_user = db.get(User, employee.user_id)
    send_email(
        to=employee_user.email,
        subject="Onboarding checklist assigned",
        body=f"Your onboarding checklist '{template.name}' has {len(template_tasks)} task(s) to complete.",
    )
    notify(
        db, user_id=employee_user.id, category=NotificationCategory.ONBOARDING,
        title="Onboarding checklist assigned",
        body=f"'{template.name}' has {len(template_tasks)} task(s) to complete.",
    )
    return _to_response(db, onboarding)


@router.get("/me", response_model=list[EmployeeOnboardingResponse])
def my_onboarding(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[EmployeeOnboardingResponse]:
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        return []
    onboardings = list(db.scalars(select(EmployeeOnboarding).where(EmployeeOnboarding.employee_id == employee.id)))
    return [_to_response(db, o) for o in onboardings]


@router.get("/employee/{employee_id}", response_model=list[EmployeeOnboardingResponse])
def employee_onboarding_list(
    employee_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[EmployeeOnboardingResponse]:
    employee = db.scalar(
        select(Employee).where(
            Employee.id == employee_id, Employee.company_id == current_user.company_id, Employee.deleted_at.is_(None)
        )
    )
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    if employee.user_id != current_user.id and current_user.role.value not in HR_WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    onboardings = list(db.scalars(select(EmployeeOnboarding).where(EmployeeOnboarding.employee_id == employee.id)))
    return [_to_response(db, o) for o in onboardings]


@router.put("/tasks/{employee_onboarding_task_id}", response_model=EmployeeOnboardingTaskResponse)
def update_task_status(
    employee_onboarding_task_id: int,
    payload: UpdateOnboardingTaskStatusRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmployeeOnboardingTaskResponse:
    eot = db.get(EmployeeOnboardingTask, employee_onboarding_task_id)
    if eot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding task not found")

    onboarding = db.get(EmployeeOnboarding, eot.onboarding_id)
    employee = db.get(Employee, onboarding.employee_id)
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onboarding task not found")

    is_assignee = eot.assigned_to_user_id == current_user.id
    is_hr = current_user.role.value in HR_WRITE_ROLES
    if not is_assignee and not is_hr:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    eot.status = payload.status
    if payload.notes is not None:
        eot.notes = payload.notes
    if payload.status == OnboardingTaskStatus.COMPLETED:
        eot.completed_at = utcnow()
    db.commit()
    db.refresh(eot)

    log_audit(
        db,
        user_id=current_user.id,
        action="onboarding_task_status_updated",
        entity_type="employee_onboarding_task",
        entity_id=eot.id,
        ip_address=get_client_ip(request),
    )

    remaining = db.scalar(
        select(EmployeeOnboardingTask).where(
            EmployeeOnboardingTask.onboarding_id == onboarding.id,
            EmployeeOnboardingTask.status != OnboardingTaskStatus.COMPLETED,
        )
    )
    if remaining is None and onboarding.status != OnboardingStatus.COMPLETED:
        onboarding.status = OnboardingStatus.COMPLETED
        onboarding.completed_at = utcnow()
        db.commit()
        employee_user = db.get(User, employee.user_id)
        send_email(
            to=employee_user.email,
            subject="Onboarding completed",
            body="All onboarding tasks have been completed. Welcome aboard!",
        )
        notify(
            db, user_id=employee_user.id, category=NotificationCategory.ONBOARDING,
            title="Onboarding completed", body="All onboarding tasks have been completed. Welcome aboard!",
        )
        notify_many(
            db, user_ids=hr_user_ids(db, current_user.company_id), category=NotificationCategory.ONBOARDING,
            title="Onboarding completed",
            body=f"{employee_user.full_name} has completed their onboarding checklist.",
            link="/hr/onboarding",
        )

    task = db.get(OnboardingTask, eot.task_id)
    return EmployeeOnboardingTaskResponse(
        id=eot.id,
        task_id=eot.task_id,
        title=task.title,
        status=eot.status,
        assigned_to_user_id=eot.assigned_to_user_id,
        due_date=eot.due_date,
        completed_at=eot.completed_at,
        notes=eot.notes,
    )
