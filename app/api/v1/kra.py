from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES, get_client_ip, get_current_user, get_db, require_role
from app.core.audit import log_audit
from app.core.notifications import hr_user_ids, notify, notify_many
from app.models.appraisal import AppraisalCycle, AppraisalCycleStatus
from app.models.employee import Employee
from app.models.kra import EmployeeKra, EmployeeKraItem, KraStatus, KraTemplate, KraTemplateItem
from app.models.mixins import utcnow
from app.models.notification import NotificationCategory
from app.models.user import User
from app.schemas.kra import (
    AppraisalCycleCreate,
    AppraisalCycleResponse,
    AppraisalCycleUpdate,
    AssignKraRequest,
    EmployeeKraDetail,
    EmployeeKraItemResponse,
    EmployeeKraResponse,
    KraTemplateCreate,
    KraTemplateDetail,
    KraTemplateItemCreate,
    KraTemplateItemResponse,
    KraTemplateItemUpdate,
    KraTemplateResponse,
    KraTemplateUpdate,
    ManagerRatingRequest,
    SelfRatingRequest,
)

router = APIRouter(prefix="/kra", tags=["kra"])

WEIGHTAGE_TOLERANCE = 0.01


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


def _current_employee_or_none(db: Session, current_user: User) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))


def _get_cycle_or_404(db: Session, cycle_id: int, company_id: int | None) -> AppraisalCycle:
    cycle = db.scalar(
        select(AppraisalCycle).where(
            AppraisalCycle.id == cycle_id, AppraisalCycle.company_id == company_id, AppraisalCycle.deleted_at.is_(None)
        )
    )
    if cycle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appraisal cycle not found")
    return cycle


def _get_template_or_404(db: Session, template_id: int, company_id: int | None) -> KraTemplate:
    template = db.scalar(
        select(KraTemplate).where(
            KraTemplate.id == template_id, KraTemplate.company_id == company_id, KraTemplate.deleted_at.is_(None)
        )
    )
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KRA template not found")
    return template


def _get_template_item_or_404(db: Session, template_id: int, item_id: int) -> KraTemplateItem:
    item = db.scalar(
        select(KraTemplateItem).where(KraTemplateItem.id == item_id, KraTemplateItem.template_id == template_id)
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template item not found")
    return item


def _get_employee_kra_or_404(db: Session, employee_kra_id: int) -> EmployeeKra:
    employee_kra = db.scalar(
        select(EmployeeKra).where(EmployeeKra.id == employee_kra_id, EmployeeKra.deleted_at.is_(None))
    )
    if employee_kra is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KRA not found")
    return employee_kra


def _authorize_kra_access(db: Session, employee: Employee, current_user: User) -> None:
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KRA not found")
    is_owner = employee.user_id == current_user.id
    is_hr = current_user.role.value in HR_WRITE_ROLES
    current_employee = _current_employee_or_none(db, current_user)
    is_manager_of = current_employee is not None and employee.reporting_manager_id == current_employee.id
    if not (is_owner or is_hr or is_manager_of):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _to_cycle_response(cycle: AppraisalCycle) -> AppraisalCycleResponse:
    roles = (cycle.review_stages_json or {}).get("enabled_roles", ["self", "manager"])
    return AppraisalCycleResponse(
        id=cycle.id,
        company_id=cycle.company_id,
        name=cycle.name,
        start_date=cycle.start_date,
        end_date=cycle.end_date,
        status=cycle.status,
        enabled_reviewer_roles=roles,
    )


def _to_template_item_response(item: KraTemplateItem) -> KraTemplateItemResponse:
    return KraTemplateItemResponse(
        id=item.id,
        template_id=item.template_id,
        title=item.title,
        description=item.description,
        default_weightage=item.default_weightage,
        measurement_criteria=item.measurement_criteria,
    )


def _to_template_detail(db: Session, template: KraTemplate) -> KraTemplateDetail:
    items = list(
        db.scalars(select(KraTemplateItem).where(KraTemplateItem.template_id == template.id).order_by(KraTemplateItem.id))
    )
    return KraTemplateDetail(
        id=template.id,
        company_id=template.company_id,
        name=template.name,
        description=template.description,
        is_default=template.is_default,
        items=[_to_template_item_response(i) for i in items],
    )


def _to_employee_kra_item_response(item: EmployeeKraItem) -> EmployeeKraItemResponse:
    return EmployeeKraItemResponse(
        id=item.id,
        title=item.title,
        description=item.description,
        weightage=item.weightage,
        target=item.target,
        employee_rating=item.employee_rating,
        employee_comment=item.employee_comment,
        manager_rating=item.manager_rating,
        manager_comment=item.manager_comment,
        score=item.score,
    )


def _to_employee_kra_response(db: Session, employee_kra: EmployeeKra) -> EmployeeKraResponse:
    employee = db.get(Employee, employee_kra.employee_id)
    employee_user = db.get(User, employee.user_id)
    cycle = db.get(AppraisalCycle, employee_kra.cycle_id)
    template = db.get(KraTemplate, employee_kra.template_id)
    return EmployeeKraResponse(
        id=employee_kra.id,
        employee_id=employee.id,
        employee_name=employee_user.full_name,
        employee_code=employee.employee_code,
        cycle_id=cycle.id,
        cycle_name=cycle.name,
        template_id=template.id,
        template_name=template.name,
        status=employee_kra.status,
        overall_score=employee_kra.overall_score,
        submitted_at=employee_kra.submitted_at,
        reviewed_at=employee_kra.reviewed_at,
        approved_at=employee_kra.approved_at,
    )


def _to_employee_kra_detail(db: Session, employee_kra: EmployeeKra) -> EmployeeKraDetail:
    base = _to_employee_kra_response(db, employee_kra)
    items = list(
        db.scalars(
            select(EmployeeKraItem).where(EmployeeKraItem.employee_kra_id == employee_kra.id).order_by(EmployeeKraItem.id)
        )
    )
    return EmployeeKraDetail(**base.model_dump(), items=[_to_employee_kra_item_response(i) for i in items])


# ---- Cycles ----

@router.get("/cycles", response_model=list[AppraisalCycleResponse])
def list_cycles(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[AppraisalCycleResponse]:
    cycles = list(
        db.scalars(
            select(AppraisalCycle)
            .where(AppraisalCycle.company_id == current_user.company_id, AppraisalCycle.deleted_at.is_(None))
            .order_by(AppraisalCycle.start_date.desc())
        )
    )
    return [_to_cycle_response(c) for c in cycles]


@router.post("/cycles", response_model=AppraisalCycleResponse, status_code=status.HTTP_201_CREATED)
def create_cycle(
    payload: AppraisalCycleCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> AppraisalCycleResponse:
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_date must be on or after start_date")
    cycle = AppraisalCycle(
        company_id=current_user.company_id,
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        review_stages_json={"enabled_roles": payload.enabled_reviewer_roles},
    )
    db.add(cycle)
    db.commit()
    db.refresh(cycle)
    log_audit(
        db, user_id=current_user.id, action="appraisal_cycle_created", entity_type="appraisal_cycle",
        entity_id=cycle.id, ip_address=get_client_ip(request),
    )
    return _to_cycle_response(cycle)


@router.put("/cycles/{cycle_id}", response_model=AppraisalCycleResponse)
def update_cycle(
    cycle_id: int,
    payload: AppraisalCycleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> AppraisalCycleResponse:
    cycle = _get_cycle_or_404(db, cycle_id, current_user.company_id)
    updates = payload.model_dump(exclude_unset=True, exclude={"enabled_reviewer_roles"})
    for field, value in updates.items():
        setattr(cycle, field, value)
    if payload.enabled_reviewer_roles is not None:
        cycle.review_stages_json = {"enabled_roles": payload.enabled_reviewer_roles}
    db.commit()
    db.refresh(cycle)
    return _to_cycle_response(cycle)


# ---- Templates ----

@router.get("/templates", response_model=list[KraTemplateResponse])
def list_templates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[KraTemplate]:
    return list(
        db.scalars(
            select(KraTemplate).where(KraTemplate.company_id == current_user.company_id, KraTemplate.deleted_at.is_(None))
        )
    )


@router.post("/templates", response_model=KraTemplateDetail, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: KraTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> KraTemplateDetail:
    template = KraTemplate(company_id=current_user.company_id, **payload.model_dump())
    db.add(template)
    db.commit()
    db.refresh(template)
    log_audit(
        db, user_id=current_user.id, action="kra_template_created", entity_type="kra_template",
        entity_id=template.id, ip_address=get_client_ip(request),
    )
    return _to_template_detail(db, template)


@router.get("/templates/{template_id}", response_model=KraTemplateDetail)
def get_template(
    template_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> KraTemplateDetail:
    template = _get_template_or_404(db, template_id, current_user.company_id)
    return _to_template_detail(db, template)


@router.put("/templates/{template_id}", response_model=KraTemplateDetail)
def update_template(
    template_id: int,
    payload: KraTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> KraTemplateDetail:
    template = _get_template_or_404(db, template_id, current_user.company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    return _to_template_detail(db, template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> None:
    template = _get_template_or_404(db, template_id, current_user.company_id)
    template.deleted_at = utcnow()
    db.commit()


@router.post("/templates/{template_id}/items", response_model=KraTemplateDetail, status_code=status.HTTP_201_CREATED)
def add_template_item(
    template_id: int,
    payload: KraTemplateItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> KraTemplateDetail:
    template = _get_template_or_404(db, template_id, current_user.company_id)
    item = KraTemplateItem(template_id=template.id, **payload.model_dump())
    db.add(item)
    db.commit()
    return _to_template_detail(db, template)


@router.put("/templates/{template_id}/items/{item_id}", response_model=KraTemplateDetail)
def update_template_item(
    template_id: int,
    item_id: int,
    payload: KraTemplateItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> KraTemplateDetail:
    template = _get_template_or_404(db, template_id, current_user.company_id)
    item = _get_template_item_or_404(db, template_id, item_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    return _to_template_detail(db, template)


@router.delete("/templates/{template_id}/items/{item_id}", response_model=KraTemplateDetail)
def delete_template_item(
    template_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> KraTemplateDetail:
    template = _get_template_or_404(db, template_id, current_user.company_id)
    item = _get_template_item_or_404(db, template_id, item_id)
    db.delete(item)
    db.commit()
    return _to_template_detail(db, template)


# ---- Assignment ----

@router.post("/assign", response_model=EmployeeKraDetail, status_code=status.HTTP_201_CREATED)
def assign_kra(
    payload: AssignKraRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> EmployeeKraDetail:
    employee = _get_employee_or_404(db, payload.employee_id, current_user.company_id)
    cycle = _get_cycle_or_404(db, payload.cycle_id, current_user.company_id)
    template = _get_template_or_404(db, payload.template_id, current_user.company_id)

    template_items = list(
        db.scalars(select(KraTemplateItem).where(KraTemplateItem.template_id == template.id).order_by(KraTemplateItem.id))
    )
    if not template_items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template has no items")
    total_weightage = sum(i.default_weightage for i in template_items)
    if abs(total_weightage - 100) > WEIGHTAGE_TOLERANCE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template item weightages must sum to 100% (currently {total_weightage}%)",
        )

    existing = db.scalar(
        select(EmployeeKra).where(
            EmployeeKra.employee_id == employee.id,
            EmployeeKra.cycle_id == cycle.id,
            EmployeeKra.deleted_at.is_(None),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This employee already has a KRA for this cycle")

    employee_kra = EmployeeKra(employee_id=employee.id, cycle_id=cycle.id, template_id=template.id, status=KraStatus.DRAFT)
    db.add(employee_kra)
    db.flush()

    for template_item in template_items:
        db.add(
            EmployeeKraItem(
                employee_kra_id=employee_kra.id,
                title=template_item.title,
                description=template_item.description,
                weightage=template_item.default_weightage,
                target=template_item.measurement_criteria,
            )
        )
    db.commit()
    db.refresh(employee_kra)

    log_audit(
        db, user_id=current_user.id, action="kra_assigned", entity_type="employee_kra",
        entity_id=employee_kra.id, ip_address=get_client_ip(request),
    )
    employee_user = db.get(User, employee.user_id)
    notify(
        db, user_id=employee_user.id, category=NotificationCategory.KRA,
        title="A new KRA has been assigned to you",
        body=f"'{cycle.name}' using the '{template.name}' template. Rate yourself to get started.",
        link="/employee/kra",
    )
    return _to_employee_kra_detail(db, employee_kra)


# ---- Employee KRA lookup ----

@router.get("/me", response_model=list[EmployeeKraResponse])
def my_kras(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[EmployeeKraResponse]:
    employee = _get_own_employee_or_404(db, current_user)
    kras = list(
        db.scalars(
            select(EmployeeKra)
            .where(EmployeeKra.employee_id == employee.id, EmployeeKra.deleted_at.is_(None))
            .order_by(EmployeeKra.id.desc())
        )
    )
    return [_to_employee_kra_response(db, k) for k in kras]


@router.get("/team", response_model=list[EmployeeKraResponse])
def team_kras(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[EmployeeKraResponse]:
    manager_employee = _get_own_employee_or_404(db, current_user)
    kras = list(
        db.scalars(
            select(EmployeeKra)
            .join(Employee, Employee.id == EmployeeKra.employee_id)
            .where(Employee.reporting_manager_id == manager_employee.id, EmployeeKra.deleted_at.is_(None))
            .order_by(EmployeeKra.id.desc())
        )
    )
    return [_to_employee_kra_response(db, k) for k in kras]


@router.get("/employee/{employee_id}", response_model=list[EmployeeKraResponse])
def employee_kras(
    employee_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> list[EmployeeKraResponse]:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    kras = list(
        db.scalars(
            select(EmployeeKra)
            .where(EmployeeKra.employee_id == employee.id, EmployeeKra.deleted_at.is_(None))
            .order_by(EmployeeKra.id.desc())
        )
    )
    return [_to_employee_kra_response(db, k) for k in kras]


@router.get("", response_model=list[EmployeeKraResponse])
def list_all_kras(
    status_filter: KraStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> list[EmployeeKraResponse]:
    query = (
        select(EmployeeKra)
        .join(Employee, Employee.id == EmployeeKra.employee_id)
        .where(Employee.company_id == current_user.company_id, EmployeeKra.deleted_at.is_(None))
    )
    if status_filter is not None:
        query = query.where(EmployeeKra.status == status_filter)
    kras = list(db.scalars(query.order_by(EmployeeKra.id.desc())))
    return [_to_employee_kra_response(db, k) for k in kras]


@router.get("/{kra_id}", response_model=EmployeeKraDetail)
def get_kra(kra_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> EmployeeKraDetail:
    employee_kra = _get_employee_kra_or_404(db, kra_id)
    employee = db.get(Employee, employee_kra.employee_id)
    _authorize_kra_access(db, employee, current_user)
    return _to_employee_kra_detail(db, employee_kra)


# ---- Employee self-rating ----

@router.put("/{kra_id}/self-rating", response_model=EmployeeKraDetail)
def update_self_rating(
    kra_id: int,
    payload: SelfRatingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmployeeKraDetail:
    employee_kra = _get_employee_kra_or_404(db, kra_id)
    employee = db.get(Employee, employee_kra.employee_id)
    if employee.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only rate your own KRA")
    if employee_kra.status != KraStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This KRA is not open for self-rating")

    items_by_id = {
        item.id: item
        for item in db.scalars(select(EmployeeKraItem).where(EmployeeKraItem.employee_kra_id == employee_kra.id))
    }
    for rating in payload.items:
        item = items_by_id.get(rating.item_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Item {rating.item_id} not found on this KRA")
        item.employee_rating = rating.rating
        item.employee_comment = rating.comment
    db.commit()
    db.refresh(employee_kra)
    return _to_employee_kra_detail(db, employee_kra)


@router.post("/{kra_id}/submit", response_model=EmployeeKraDetail)
def submit_kra(
    kra_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmployeeKraDetail:
    employee_kra = _get_employee_kra_or_404(db, kra_id)
    employee = db.get(Employee, employee_kra.employee_id)
    if employee.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only submit your own KRA")
    if employee_kra.status != KraStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This KRA is not open for submission")

    items = list(db.scalars(select(EmployeeKraItem).where(EmployeeKraItem.employee_kra_id == employee_kra.id)))
    if any(i.employee_rating is None for i in items):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rate every item before submitting")

    employee_kra.status = KraStatus.SUBMITTED
    employee_kra.submitted_at = utcnow()
    db.commit()
    db.refresh(employee_kra)

    log_audit(
        db, user_id=current_user.id, action="kra_submitted", entity_type="employee_kra",
        entity_id=employee_kra.id, ip_address=get_client_ip(request),
    )
    manager = db.get(Employee, employee.reporting_manager_id) if employee.reporting_manager_id else None
    manager_user = db.get(User, manager.user_id) if manager else None
    if manager_user is not None:
        notify(
            db, user_id=manager_user.id, category=NotificationCategory.KRA,
            title="A KRA is awaiting your review",
            body=f"{current_user.full_name} submitted their KRA for review.",
            link="/manager/team-leave",
        )
    else:
        notify_many(
            db, user_ids=hr_user_ids(db, current_user.company_id), category=NotificationCategory.KRA,
            title="A KRA is awaiting review",
            body=f"{current_user.full_name} submitted their KRA for review.",
            link="/hr/kra",
        )
    return _to_employee_kra_detail(db, employee_kra)


# ---- Manager rating ----

def _authorize_manager_stage(db: Session, employee: Employee, current_user: User) -> None:
    current_employee = _current_employee_or_none(db, current_user)
    is_manager_of = current_employee is not None and employee.reporting_manager_id == current_employee.id
    is_hr = current_user.role.value in HR_WRITE_ROLES
    if not (is_manager_of or is_hr):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the assigned reporting manager or HR can act at this stage"
        )


@router.put("/{kra_id}/manager-rating", response_model=EmployeeKraDetail)
def update_manager_rating(
    kra_id: int,
    payload: ManagerRatingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmployeeKraDetail:
    employee_kra = _get_employee_kra_or_404(db, kra_id)
    employee = db.get(Employee, employee_kra.employee_id)
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KRA not found")
    _authorize_manager_stage(db, employee, current_user)
    if employee_kra.status != KraStatus.SUBMITTED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This KRA is not awaiting manager rating")

    items_by_id = {
        item.id: item
        for item in db.scalars(select(EmployeeKraItem).where(EmployeeKraItem.employee_kra_id == employee_kra.id))
    }
    for rating in payload.items:
        item = items_by_id.get(rating.item_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Item {rating.item_id} not found on this KRA")
        item.manager_rating = rating.rating
        item.manager_comment = rating.comment
    db.commit()
    db.refresh(employee_kra)
    return _to_employee_kra_detail(db, employee_kra)


@router.post("/{kra_id}/complete-review", response_model=EmployeeKraDetail)
def complete_review(
    kra_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EmployeeKraDetail:
    employee_kra = _get_employee_kra_or_404(db, kra_id)
    employee = db.get(Employee, employee_kra.employee_id)
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KRA not found")
    _authorize_manager_stage(db, employee, current_user)
    if employee_kra.status != KraStatus.SUBMITTED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This KRA is not awaiting manager review")

    items = list(db.scalars(select(EmployeeKraItem).where(EmployeeKraItem.employee_kra_id == employee_kra.id)))
    if any(i.manager_rating is None for i in items):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rate every item before completing the review")

    for item in items:
        item.score = item.manager_rating * item.weightage / 100

    employee_kra.status = KraStatus.REVIEWED
    employee_kra.reviewed_at = utcnow()
    db.commit()
    db.refresh(employee_kra)

    log_audit(
        db, user_id=current_user.id, action="kra_review_completed", entity_type="employee_kra",
        entity_id=employee_kra.id, ip_address=get_client_ip(request),
    )
    employee_user = db.get(User, employee.user_id)
    notify_many(
        db, user_ids=hr_user_ids(db, current_user.company_id), category=NotificationCategory.KRA,
        title="A KRA is awaiting HR approval",
        body=f"{employee_user.full_name}'s KRA has been reviewed and needs final approval.",
        link="/hr/kra",
    )
    return _to_employee_kra_detail(db, employee_kra)


# ---- HR approval ----

@router.post("/{kra_id}/approve", response_model=EmployeeKraDetail)
def approve_kra(
    kra_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> EmployeeKraDetail:
    employee_kra = _get_employee_kra_or_404(db, kra_id)
    employee = db.get(Employee, employee_kra.employee_id)
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KRA not found")
    if employee_kra.status != KraStatus.REVIEWED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This KRA is not awaiting HR approval")

    items = list(db.scalars(select(EmployeeKraItem).where(EmployeeKraItem.employee_kra_id == employee_kra.id)))
    employee_kra.overall_score = sum(i.score or 0 for i in items)
    employee_kra.status = KraStatus.APPROVED
    employee_kra.approved_at = utcnow()
    db.commit()
    db.refresh(employee_kra)

    log_audit(
        db, user_id=current_user.id, action="kra_approved", entity_type="employee_kra",
        entity_id=employee_kra.id, ip_address=get_client_ip(request),
    )
    employee_user = db.get(User, employee.user_id)
    notify(
        db, user_id=employee_user.id, category=NotificationCategory.KRA,
        title="Your KRA has been approved",
        body=f"Your overall score is {employee_kra.overall_score:.2f}.",
        link="/employee/kra",
    )
    return _to_employee_kra_detail(db, employee_kra)
