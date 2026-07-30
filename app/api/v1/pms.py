from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import HR_WRITE_ROLES, get_client_ip, get_current_user, get_db, require_role
from app.core.audit import log_audit
from app.core.notifications import hr_user_ids, notify, notify_many
from app.models.appraisal import AppraisalCycle
from app.models.designation import Designation
from app.models.employee import Employee
from app.models.mixins import utcnow
from app.models.notification import NotificationCategory
from app.models.pms import (
    Competency,
    PmsEvaluation,
    PmsEvaluationItem,
    PmsReviewerRole,
    PmsReviewRequest,
    PmsReviewRequestStatus,
    PromotionRecommendation,
    RatingScale,
)
from app.models.user import User
from app.schemas.pms import (
    AssignEmployeeRequest,
    AssignReviewerRequest,
    CompetencyCreate,
    CompetencyResponse,
    CompetencyUpdate,
    CompletionRow,
    EmployeeNormalizationRow,
    NormalizationBucket,
    NormalizationResponse,
    PmsEvaluationItemResponse,
    PmsEvaluationResponse,
    PmsReviewRequestResponse,
    PromotionRecommendationCreate,
    PromotionRecommendationResponse,
    PromotionRecommendationUpdate,
    RatingScaleCreate,
    RatingScaleResponse,
    RatingScaleUpdate,
    SubmitEvaluationRequest,
)

router = APIRouter(prefix="/pms", tags=["pms"])


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


def _get_competency_or_404(db: Session, competency_id: int, company_id: int | None) -> Competency:
    competency = db.scalar(
        select(Competency).where(
            Competency.id == competency_id, Competency.company_id == company_id, Competency.deleted_at.is_(None)
        )
    )
    if competency is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competency not found")
    return competency


def _get_rating_scale_or_404(db: Session, scale_id: int, company_id: int | None) -> RatingScale:
    scale = db.scalar(
        select(RatingScale).where(
            RatingScale.id == scale_id, RatingScale.company_id == company_id, RatingScale.deleted_at.is_(None)
        )
    )
    if scale is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating scale not found")
    return scale


def _get_review_request_or_404(db: Session, request_id: int) -> PmsReviewRequest:
    review_request = db.get(PmsReviewRequest, request_id)
    if review_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review request not found")
    return review_request


def _authorize_employee_access(db: Session, employee: Employee, current_user: User) -> None:
    if employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    is_owner = employee.user_id == current_user.id
    is_hr = current_user.role.value in HR_WRITE_ROLES
    current_employee = _current_employee_or_none(db, current_user)
    is_manager_of = current_employee is not None and employee.reporting_manager_id == current_employee.id
    if not (is_owner or is_hr or is_manager_of):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _to_rating_scale_response(scale: RatingScale) -> RatingScaleResponse:
    return RatingScaleResponse(
        id=scale.id,
        company_id=scale.company_id,
        name=scale.name,
        min_score=scale.min_score,
        max_score=scale.max_score,
        description=scale.description,
        descriptors=scale.descriptors_json,
    )


def _to_review_request_response(db: Session, review_request: PmsReviewRequest) -> PmsReviewRequestResponse:
    employee = db.get(Employee, review_request.employee_id)
    employee_user = db.get(User, employee.user_id)
    cycle = db.get(AppraisalCycle, review_request.cycle_id)
    return PmsReviewRequestResponse(
        id=review_request.id,
        employee_id=employee.id,
        employee_name=employee_user.full_name,
        employee_code=employee.employee_code,
        cycle_id=cycle.id,
        cycle_name=cycle.name,
        reviewer_role=review_request.reviewer_role,
        status=review_request.status,
        requested_at=review_request.requested_at,
    )


def _to_evaluation_response(db: Session, evaluation: PmsEvaluation) -> PmsEvaluationResponse:
    evaluator = db.get(User, evaluation.evaluator_id)
    items = list(
        db.scalars(select(PmsEvaluationItem).where(PmsEvaluationItem.evaluation_id == evaluation.id))
    )
    item_responses = []
    for item in items:
        competency = db.get(Competency, item.competency_id)
        item_responses.append(
            PmsEvaluationItemResponse(
                competency_id=item.competency_id,
                competency_name=competency.name if competency else "Unknown",
                rating=item.rating,
                comment=item.comment,
            )
        )
    return PmsEvaluationResponse(
        id=evaluation.id,
        employee_id=evaluation.employee_id,
        cycle_id=evaluation.cycle_id,
        evaluator_id=evaluation.evaluator_id,
        evaluator_name=evaluator.full_name if evaluator else "Unknown",
        evaluator_role=evaluation.evaluator_role,
        submitted_at=evaluation.submitted_at,
        items=item_responses,
    )


def _to_promotion_response(db: Session, promo: PromotionRecommendation) -> PromotionRecommendationResponse:
    employee = db.get(Employee, promo.employee_id)
    employee_user = db.get(User, employee.user_id)
    cycle = db.get(AppraisalCycle, promo.cycle_id)
    recommender = db.get(User, promo.recommended_by)
    designation = db.get(Designation, promo.recommended_designation_id) if promo.recommended_designation_id else None
    return PromotionRecommendationResponse(
        id=promo.id,
        employee_id=employee.id,
        employee_name=employee_user.full_name,
        employee_code=employee.employee_code,
        cycle_id=cycle.id,
        cycle_name=cycle.name,
        recommended_by=promo.recommended_by,
        recommended_by_name=recommender.full_name if recommender else "Unknown",
        recommended_designation_id=promo.recommended_designation_id,
        recommended_designation_name=designation.name if designation else None,
        reason=promo.reason,
        status=promo.status,
    )


# ---- Competencies ----

@router.get("/competencies", response_model=list[CompetencyResponse])
def list_competencies(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[Competency]:
    return list(
        db.scalars(
            select(Competency).where(Competency.company_id == current_user.company_id, Competency.deleted_at.is_(None))
        )
    )


@router.post("/competencies", response_model=CompetencyResponse, status_code=status.HTTP_201_CREATED)
def create_competency(
    payload: CompetencyCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> Competency:
    competency = Competency(company_id=current_user.company_id, **payload.model_dump())
    db.add(competency)
    db.commit()
    db.refresh(competency)
    log_audit(
        db, user_id=current_user.id, action="pms_competency_created", entity_type="competency",
        entity_id=competency.id, ip_address=get_client_ip(request),
    )
    return competency


@router.put("/competencies/{competency_id}", response_model=CompetencyResponse)
def update_competency(
    competency_id: int,
    payload: CompetencyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> Competency:
    competency = _get_competency_or_404(db, competency_id, current_user.company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(competency, field, value)
    db.commit()
    db.refresh(competency)
    return competency


@router.delete("/competencies/{competency_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_competency(
    competency_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> None:
    competency = _get_competency_or_404(db, competency_id, current_user.company_id)
    competency.deleted_at = utcnow()
    db.commit()


# ---- Rating scales ----

@router.get("/rating-scales", response_model=list[RatingScaleResponse])
def list_rating_scales(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[RatingScaleResponse]:
    scales = list(
        db.scalars(
            select(RatingScale).where(RatingScale.company_id == current_user.company_id, RatingScale.deleted_at.is_(None))
        )
    )
    return [_to_rating_scale_response(s) for s in scales]


@router.post("/rating-scales", response_model=RatingScaleResponse, status_code=status.HTTP_201_CREATED)
def create_rating_scale(
    payload: RatingScaleCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> RatingScaleResponse:
    if payload.max_score <= payload.min_score:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="max_score must be greater than min_score")
    scale = RatingScale(
        company_id=current_user.company_id,
        name=payload.name,
        min_score=payload.min_score,
        max_score=payload.max_score,
        description=payload.description,
        descriptors_json=payload.descriptors,
    )
    db.add(scale)
    db.commit()
    db.refresh(scale)
    log_audit(
        db, user_id=current_user.id, action="pms_rating_scale_created", entity_type="rating_scale",
        entity_id=scale.id, ip_address=get_client_ip(request),
    )
    return _to_rating_scale_response(scale)


@router.put("/rating-scales/{scale_id}", response_model=RatingScaleResponse)
def update_rating_scale(
    scale_id: int,
    payload: RatingScaleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> RatingScaleResponse:
    scale = _get_rating_scale_or_404(db, scale_id, current_user.company_id)
    updates = payload.model_dump(exclude_unset=True, exclude={"descriptors"})
    for field, value in updates.items():
        setattr(scale, field, value)
    if payload.descriptors is not None:
        scale.descriptors_json = payload.descriptors
    db.commit()
    db.refresh(scale)
    return _to_rating_scale_response(scale)


@router.delete("/rating-scales/{scale_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rating_scale(
    scale_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> None:
    scale = _get_rating_scale_or_404(db, scale_id, current_user.company_id)
    scale.deleted_at = utcnow()
    db.commit()


# ---- Reviewer assignment ----

@router.post("/cycles/{cycle_id}/assign-employee", response_model=list[PmsReviewRequestResponse])
def assign_employee_to_cycle(
    cycle_id: int,
    payload: AssignEmployeeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> list[PmsReviewRequestResponse]:
    cycle = _get_cycle_or_404(db, cycle_id, current_user.company_id)
    employee = _get_employee_or_404(db, payload.employee_id, current_user.company_id)
    newly_created_reviewer_ids: list[int] = []

    def _ensure_request(reviewer_user_id: int, role: PmsReviewerRole) -> PmsReviewRequest:
        existing = db.scalar(
            select(PmsReviewRequest).where(
                PmsReviewRequest.employee_id == employee.id,
                PmsReviewRequest.cycle_id == cycle.id,
                PmsReviewRequest.reviewer_role == role,
                PmsReviewRequest.reviewer_user_id == reviewer_user_id,
            )
        )
        if existing is not None:
            return existing
        review_request = PmsReviewRequest(
            employee_id=employee.id, cycle_id=cycle.id, reviewer_user_id=reviewer_user_id, reviewer_role=role
        )
        db.add(review_request)
        db.flush()
        newly_created_reviewer_ids.append(reviewer_user_id)
        return review_request

    created = [_ensure_request(employee.user_id, PmsReviewerRole.SELF)]
    if employee.reporting_manager_id:
        manager = db.get(Employee, employee.reporting_manager_id)
        if manager is not None:
            created.append(_ensure_request(manager.user_id, PmsReviewerRole.MANAGER))

    db.commit()
    for review_request in created:
        db.refresh(review_request)

    log_audit(
        db, user_id=current_user.id, action="pms_employee_assigned", entity_type="appraisal_cycle",
        entity_id=cycle.id, ip_address=get_client_ip(request),
    )
    notify_many(
        db, user_ids=newly_created_reviewer_ids, category=NotificationCategory.PMS,
        title="You have a new performance review to complete",
        body=f"A review for '{cycle.name}' is waiting for you.",
        link="/employee/pms",
    )
    return [_to_review_request_response(db, r) for r in created]


@router.post("/cycles/{cycle_id}/assign-reviewer", response_model=PmsReviewRequestResponse, status_code=status.HTTP_201_CREATED)
def assign_reviewer(
    cycle_id: int,
    payload: AssignReviewerRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> PmsReviewRequestResponse:
    cycle = _get_cycle_or_404(db, cycle_id, current_user.company_id)
    employee = _get_employee_or_404(db, payload.employee_id, current_user.company_id)

    reviewer_user = db.scalar(
        select(User).where(User.id == payload.reviewer_user_id, User.company_id == current_user.company_id)
    )
    if reviewer_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reviewer not found")

    role = PmsReviewerRole(payload.reviewer_role)
    existing = db.scalar(
        select(PmsReviewRequest).where(
            PmsReviewRequest.employee_id == employee.id,
            PmsReviewRequest.cycle_id == cycle.id,
            PmsReviewRequest.reviewer_role == role,
            PmsReviewRequest.reviewer_user_id == reviewer_user.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reviewer is already assigned for this role")

    review_request = PmsReviewRequest(
        employee_id=employee.id,
        cycle_id=cycle.id,
        reviewer_user_id=reviewer_user.id,
        reviewer_role=role,
        requested_by=current_user.id,
    )
    db.add(review_request)
    db.commit()
    db.refresh(review_request)

    log_audit(
        db, user_id=current_user.id, action="pms_reviewer_assigned", entity_type="pms_review_request",
        entity_id=review_request.id, ip_address=get_client_ip(request),
    )
    employee_user = db.get(User, employee.user_id)
    notify(
        db, user_id=reviewer_user.id, category=NotificationCategory.PMS,
        title="You have a new performance review to complete",
        body=f"You've been asked to give {role.value} feedback for {employee_user.full_name} in '{cycle.name}'.",
        link="/employee/pms",
    )
    return _to_review_request_response(db, review_request)


# ---- Evaluation submission ----

@router.get("/requests/me", response_model=list[PmsReviewRequestResponse])
def my_review_requests(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[PmsReviewRequestResponse]:
    requests = list(
        db.scalars(
            select(PmsReviewRequest)
            .where(PmsReviewRequest.reviewer_user_id == current_user.id)
            .order_by(PmsReviewRequest.requested_at.desc())
        )
    )
    return [_to_review_request_response(db, r) for r in requests]


@router.post("/evaluations", response_model=PmsEvaluationResponse, status_code=status.HTTP_201_CREATED)
def submit_evaluation(
    payload: SubmitEvaluationRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PmsEvaluationResponse:
    review_request = _get_review_request_or_404(db, payload.review_request_id)
    if review_request.reviewer_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This review request is not assigned to you")
    if review_request.status != PmsReviewRequestStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This review has already been completed")
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rate at least one competency")

    scale = db.scalar(
        select(RatingScale).where(RatingScale.company_id == current_user.company_id, RatingScale.deleted_at.is_(None))
    )
    if scale is not None:
        for item in payload.items:
            if not (scale.min_score <= item.rating <= scale.max_score):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Rating must be between {scale.min_score} and {scale.max_score}",
                )

    evaluation = PmsEvaluation(
        employee_id=review_request.employee_id,
        cycle_id=review_request.cycle_id,
        evaluator_id=current_user.id,
        evaluator_role=review_request.reviewer_role,
        review_request_id=review_request.id,
    )
    db.add(evaluation)
    db.flush()

    for item in payload.items:
        _get_competency_or_404(db, item.competency_id, current_user.company_id)
        db.add(
            PmsEvaluationItem(
                evaluation_id=evaluation.id, competency_id=item.competency_id, rating=item.rating, comment=item.comment
            )
        )

    review_request.status = PmsReviewRequestStatus.COMPLETED
    db.commit()
    db.refresh(evaluation)

    log_audit(
        db, user_id=current_user.id, action="pms_evaluation_submitted", entity_type="pms_evaluation",
        entity_id=evaluation.id, ip_address=get_client_ip(request),
    )
    return _to_evaluation_response(db, evaluation)


@router.get("/employee/{employee_id}", response_model=list[PmsEvaluationResponse])
def employee_evaluations(
    employee_id: int,
    cycle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PmsEvaluationResponse]:
    employee = _get_employee_or_404(db, employee_id, current_user.company_id)
    _authorize_employee_access(db, employee, current_user)

    evaluations = list(
        db.scalars(
            select(PmsEvaluation).where(PmsEvaluation.employee_id == employee.id, PmsEvaluation.cycle_id == cycle_id)
        )
    )
    return [_to_evaluation_response(db, e) for e in evaluations]


# ---- Completion tracking & normalization ----

@router.get("/cycles/{cycle_id}/completion", response_model=list[CompletionRow])
def cycle_completion(
    cycle_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> list[CompletionRow]:
    cycle = _get_cycle_or_404(db, cycle_id, current_user.company_id)

    requests = list(db.scalars(select(PmsReviewRequest).where(PmsReviewRequest.cycle_id == cycle.id)))
    by_employee: dict[int, list[PmsReviewRequest]] = {}
    for r in requests:
        by_employee.setdefault(r.employee_id, []).append(r)

    rows = []
    for employee_id, employee_requests in by_employee.items():
        employee = db.get(Employee, employee_id)
        if employee is None:
            continue
        employee_user = db.get(User, employee.user_id)
        completed = sum(1 for r in employee_requests if r.status == PmsReviewRequestStatus.COMPLETED)
        rows.append(
            CompletionRow(
                employee_id=employee.id,
                employee_name=employee_user.full_name,
                employee_code=employee.employee_code,
                total_requests=len(employee_requests),
                completed_requests=completed,
            )
        )
    rows.sort(key=lambda r: r.employee_name)
    return rows


@router.get("/cycles/{cycle_id}/normalization", response_model=NormalizationResponse)
def cycle_normalization(
    cycle_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*HR_WRITE_ROLES))
) -> NormalizationResponse:
    cycle = _get_cycle_or_404(db, cycle_id, current_user.company_id)

    scale = db.scalar(
        select(RatingScale).where(RatingScale.company_id == current_user.company_id, RatingScale.deleted_at.is_(None))
    )
    scale_min = scale.min_score if scale else 1.0
    scale_max = scale.max_score if scale else 5.0

    manager_evaluations = list(
        db.scalars(
            select(PmsEvaluation).where(
                PmsEvaluation.cycle_id == cycle.id, PmsEvaluation.evaluator_role == PmsReviewerRole.MANAGER
            )
        )
    )

    employee_rows = []
    scores: list[float] = []
    for evaluation in manager_evaluations:
        employee = db.get(Employee, evaluation.employee_id)
        if employee is None:
            continue
        employee_user = db.get(User, employee.user_id)
        items = list(db.scalars(select(PmsEvaluationItem).where(PmsEvaluationItem.evaluation_id == evaluation.id)))
        average = sum(i.rating for i in items) / len(items) if items else None
        if average is not None:
            scores.append(average)
        employee_rows.append(
            EmployeeNormalizationRow(
                employee_id=employee.id,
                employee_name=employee_user.full_name,
                employee_code=employee.employee_code,
                manager_average=average,
            )
        )
    employee_rows.sort(key=lambda r: r.employee_name)

    band_count = 5
    band_width = (scale_max - scale_min) / band_count
    buckets = []
    for i in range(band_count):
        band_min = scale_min + i * band_width
        band_max = scale_max if i == band_count - 1 else band_min + band_width
        count = sum(
            1
            for s in scores
            if (band_min <= s < band_max) or (i == band_count - 1 and s == band_max)
        )
        buckets.append(
            NormalizationBucket(label=f"{band_min:.1f} - {band_max:.1f}", band_min=band_min, band_max=band_max, count=count)
        )

    return NormalizationResponse(buckets=buckets, employees=employee_rows)


# ---- Promotion recommendations ----

@router.get("/promotions", response_model=list[PromotionRecommendationResponse])
def list_promotions(
    cycle_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PromotionRecommendationResponse]:
    query = (
        select(PromotionRecommendation)
        .join(Employee, Employee.id == PromotionRecommendation.employee_id)
        .where(Employee.company_id == current_user.company_id)
    )
    is_hr = current_user.role.value in HR_WRITE_ROLES
    if not is_hr:
        current_employee = _current_employee_or_none(db, current_user)
        if current_employee is None:
            return []
        query = query.where(
            (PromotionRecommendation.recommended_by == current_user.id)
            | (Employee.reporting_manager_id == current_employee.id)
        )
    if cycle_id is not None:
        query = query.where(PromotionRecommendation.cycle_id == cycle_id)
    promos = list(db.scalars(query.order_by(PromotionRecommendation.id.desc())))
    return [_to_promotion_response(db, p) for p in promos]


@router.post("/promotions", response_model=PromotionRecommendationResponse, status_code=status.HTTP_201_CREATED)
def create_promotion(
    payload: PromotionRecommendationCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PromotionRecommendationResponse:
    employee = _get_employee_or_404(db, payload.employee_id, current_user.company_id)
    _get_cycle_or_404(db, payload.cycle_id, current_user.company_id)

    is_hr = current_user.role.value in HR_WRITE_ROLES
    current_employee = _current_employee_or_none(db, current_user)
    is_manager_of = current_employee is not None and employee.reporting_manager_id == current_employee.id
    if not (is_hr or is_manager_of):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only HR or the reporting manager can recommend a promotion")

    if payload.recommended_designation_id is not None:
        designation = db.scalar(
            select(Designation).where(
                Designation.id == payload.recommended_designation_id,
                Designation.company_id == current_user.company_id,
                Designation.deleted_at.is_(None),
            )
        )
        if designation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Designation not found")

    promo = PromotionRecommendation(
        employee_id=employee.id,
        cycle_id=payload.cycle_id,
        recommended_by=current_user.id,
        recommended_designation_id=payload.recommended_designation_id,
        reason=payload.reason,
    )
    db.add(promo)
    db.commit()
    db.refresh(promo)

    log_audit(
        db, user_id=current_user.id, action="pms_promotion_recommended", entity_type="promotion_recommendation",
        entity_id=promo.id, ip_address=get_client_ip(request),
    )
    employee_user = db.get(User, employee.user_id)
    notify_many(
        db, user_ids=hr_user_ids(db, current_user.company_id, exclude_user_id=current_user.id),
        category=NotificationCategory.PMS,
        title="A promotion has been recommended",
        body=f"{current_user.full_name} recommended {employee_user.full_name} for promotion.",
        link="/hr/pms",
    )
    return _to_promotion_response(db, promo)


@router.put("/promotions/{promotion_id}", response_model=PromotionRecommendationResponse)
def update_promotion(
    promotion_id: int,
    payload: PromotionRecommendationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*HR_WRITE_ROLES)),
) -> PromotionRecommendationResponse:
    promo = db.get(PromotionRecommendation, promotion_id)
    if promo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion recommendation not found")
    employee = db.get(Employee, promo.employee_id)
    if employee is None or employee.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion recommendation not found")

    promo.status = payload.status
    db.commit()
    db.refresh(promo)

    log_audit(
        db, user_id=current_user.id, action=f"pms_promotion_{payload.status.value}", entity_type="promotion_recommendation",
        entity_id=promo.id, ip_address=get_client_ip(request),
    )
    employee_user = db.get(User, employee.user_id)
    notify(
        db, user_id=employee_user.id, category=NotificationCategory.PMS,
        title=f"Your promotion recommendation was {payload.status.value}",
        link="/employee/pms",
    )
    if promo.recommended_by != current_user.id:
        notify(
            db, user_id=promo.recommended_by, category=NotificationCategory.PMS,
            title=f"Promotion recommendation for {employee_user.full_name} was {payload.status.value}",
            link="/hr/pms",
        )
    return _to_promotion_response(db, promo)
