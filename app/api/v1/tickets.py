import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, get_current_user, get_db
from app.api.v1.ticket_permissions import PROJECT_ROLES, get_project_role, require_permission
from app.core.audit import log_audit
from app.core.files import copy_ticket_attachment, delete_file_if_exists, save_ticket_attachment
from app.core.notifications import notify
from app.models.employee import Employee
from app.models.mixins import utcnow
from app.models.notification import NotificationCategory
from app.models.project import (
    Project,
    ProjectMember,
    ProjectWatcher,
    Sprint,
    SprintProject,
    SprintStatus,
    StatusCategory,
    TicketStatus,
)
from app.models.ticket import (
    IssueType,
    Label,
    Ticket,
    TicketActivity,
    TicketAttachment,
    TicketComment,
    TicketLabel,
    TicketPriority,
    TicketWatcher,
    WorkLog,
)
from app.models.user import User
from app.schemas.ticket import (
    BacklogResponse,
    BoardProjectSummary,
    BoardResponse,
    GlobalBoardResponse,
    IssueTypeCreate,
    IssueTypeResponse,
    LabelCreate,
    LabelResponse,
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberResponse,
    ProjectMemberRoleUpdate,
    ProjectResponse,
    ProjectUpdate,
    SprintCompleteRequest,
    SprintCreate,
    SprintDetailResponse,
    SprintMemberWorkload,
    SprintProjectBreakdown,
    SprintResponse,
    SprintUpdate,
    TicketActivityResponse,
    TicketAttachmentResponse,
    TicketBulkUpdateRequest,
    TicketBulkUpdateResponse,
    TicketCategoryUpdate,
    TicketCloneRequest,
    TicketCommentCreate,
    TicketCommentResponse,
    TicketCommentUpdate,
    TicketCreate,
    TicketDetailResponse,
    TicketLabelAssign,
    TicketListItem,
    TicketRelationSummary,
    TicketPositionUpdate,
    TicketPriorityCreate,
    TicketPriorityResponse,
    TicketSprintAssign,
    TicketStatusCreate,
    TicketStatusResponse,
    TicketStatusUpdate,
    TicketTransitionRequest,
    TicketUpdate,
    TimeReportEntry,
    TimeReportResponse,
    WorkLogCreate,
    WorkLogResponse,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])
projects_router = APIRouter(prefix="/projects", tags=["tickets"])
sprints_router = APIRouter(prefix="/sprints", tags=["tickets"])
catalog_router = APIRouter(tags=["tickets"])

COMMENT_EDIT_WINDOW_MINUTES = 15

DEFAULT_ISSUE_TYPES = [
    ("Bug", "bi-bug-fill", "#dc3545"),
    ("Task", "bi-check2-square", "#0d6efd"),
    ("Story", "bi-bookmark-star-fill", "#198754"),
    ("Epic", "bi-lightning-charge-fill", "#6f42c1"),
    ("Sub-task", "bi-diagram-2-fill", "#6c757d"),
]

DEFAULT_PRIORITIES = [
    ("Highest", "bi-chevron-double-up", "#dc3545"),
    ("High", "bi-chevron-up", "#fd7e14"),
    ("Medium", "bi-dash-lg", "#ffc107"),
    ("Low", "bi-chevron-down", "#0dcaf0"),
    ("Lowest", "bi-chevron-double-down", "#6c757d"),
]

DEFAULT_STATUSES = [
    ("To Do", StatusCategory.TODO, "#6c757d"),
    ("In Progress", StatusCategory.INPROGRESS, "#0d6efd"),
    ("Done", StatusCategory.DONE, "#198754"),
]


# ---- Helpers ----

def _get_own_employee_or_404(db: Session, current_user: User) -> Employee:
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile linked to this account")
    return employee


def _employee_name(db: Session, employee_id: int | None) -> str | None:
    if employee_id is None:
        return None
    row = db.execute(
        select(User.full_name).join(Employee, Employee.user_id == User.id).where(Employee.id == employee_id)
    ).first()
    return row[0] if row else None


def _ensure_catalog(db: Session, company_id: int) -> None:
    """Lazily seeds a company's issue-type and priority catalogs the first time they're needed."""
    has_types = db.scalar(select(func.count(IssueType.id)).where(IssueType.company_id == company_id))
    if not has_types:
        for position, (name, icon, color) in enumerate(DEFAULT_ISSUE_TYPES):
            db.add(IssueType(company_id=company_id, name=name, icon=icon, color=color, position=position))
    has_priorities = db.scalar(select(func.count(TicketPriority.id)).where(TicketPriority.company_id == company_id))
    if not has_priorities:
        for position, (name, icon, color) in enumerate(DEFAULT_PRIORITIES):
            db.add(TicketPriority(company_id=company_id, name=name, icon=icon, color=color, position=position))
    db.commit()


def _get_project_or_404(db: Session, project_id: int, company_id: int | None) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.company_id == company_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _get_status_or_404(db: Session, project_id: int, status_id: int) -> TicketStatus:
    ticket_status = db.scalar(
        select(TicketStatus).where(TicketStatus.id == status_id, TicketStatus.project_id == project_id)
    )
    if ticket_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status not found")
    return ticket_status


def _sprint_project_ids(db: Session, sprint: Sprint) -> set[int]:
    linked = db.scalars(select(SprintProject.project_id).where(SprintProject.sprint_id == sprint.id))
    return {sprint.project_id, *linked}


def _set_sprint_linked_projects(db: Session, sprint: Sprint, company_id: int | None, project_ids: list[int]) -> None:
    db.query(SprintProject).filter(SprintProject.sprint_id == sprint.id).delete()
    seen: set[int] = set()
    for project_id in project_ids:
        if project_id == sprint.project_id or project_id in seen:
            continue
        _get_project_or_404(db, project_id, company_id)
        db.add(SprintProject(sprint_id=sprint.id, project_id=project_id))
        seen.add(project_id)


def _get_sprint_or_404(db: Session, project_id: int, sprint_id: int) -> Sprint:
    sprint = db.get(Sprint, sprint_id)
    if sprint is None or project_id not in _sprint_project_ids(db, sprint):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")
    return sprint


def _get_sprint_with_project_or_404(db: Session, sprint_id: int, company_id: int | None) -> tuple[Sprint, Project]:
    sprint = db.scalar(
        select(Sprint).join(Project, Project.id == Sprint.project_id).where(
            Sprint.id == sprint_id, Project.company_id == company_id
        )
    )
    if sprint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")
    return sprint, db.get(Project, sprint.project_id)


def _to_sprint_response(db: Session, sprint: Sprint) -> SprintResponse:
    project_ids = _sprint_project_ids(db, sprint)
    tickets = list(db.scalars(select(Ticket).where(Ticket.sprint_id == sprint.id, Ticket.deleted_at.is_(None))))
    done_status_ids = {
        s.id
        for s in db.scalars(
            select(TicketStatus).where(TicketStatus.project_id.in_(project_ids), TicketStatus.category == StatusCategory.DONE)
        )
    }
    total_points = sum(t.story_points or 0 for t in tickets)
    completed_points = sum(t.story_points or 0 for t in tickets if t.status_id in done_status_ids)
    return SprintResponse(
        id=sprint.id,
        project_id=sprint.project_id,
        name=sprint.name,
        goal=sprint.goal,
        status=sprint.status,
        start_date=sprint.start_date,
        end_date=sprint.end_date,
        ticket_count=len(tickets),
        completed_points=completed_points,
        total_points=total_points,
        committed_points=sprint.committed_points,
        linked_project_ids=sorted(project_ids - {sprint.project_id}),
    )


def _get_ticket_or_404(db: Session, ticket_id: int, company_id: int | None) -> Ticket:
    ticket = db.scalar(
        select(Ticket)
        .join(Project, Project.id == Ticket.project_id)
        .where(Ticket.id == ticket_id, Project.company_id == company_id, Ticket.deleted_at.is_(None))
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


def _log_activity(
    db: Session,
    *,
    ticket_id: int,
    actor_id: int,
    action: str,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    db.add(
        TicketActivity(
            ticket_id=ticket_id,
            actor_id=actor_id,
            action=action,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
        )
    )
    db.commit()


def _ticket_labels(db: Session, ticket_id: int) -> list[LabelResponse]:
    labels = list(
        db.scalars(
            select(Label).join(TicketLabel, TicketLabel.label_id == Label.id).where(TicketLabel.ticket_id == ticket_id)
        )
    )
    return [LabelResponse.model_validate(label) for label in labels]


def _to_project_response(db: Session, project: Project, current_user: User | None = None) -> ProjectResponse:
    open_count = db.scalar(
        select(func.count(Ticket.id))
        .join(TicketStatus, TicketStatus.id == Ticket.status_id)
        .where(Ticket.project_id == project.id, Ticket.deleted_at.is_(None), TicketStatus.category != StatusCategory.DONE)
    )
    my_role = "viewer"
    is_watching = False
    if current_user is not None:
        my_role = get_project_role(db, project, current_user)
        employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
        if employee is not None:
            is_watching = (
                db.scalar(
                    select(func.count(ProjectWatcher.id)).where(
                        ProjectWatcher.project_id == project.id, ProjectWatcher.employee_id == employee.id
                    )
                )
                or 0
            ) > 0
    return ProjectResponse(
        id=project.id,
        company_id=project.company_id,
        key=project.key,
        name=project.name,
        description=project.description,
        lead_id=project.lead_id,
        lead_name=_employee_name(db, project.lead_id),
        is_active=project.is_active,
        open_ticket_count=open_count or 0,
        my_role=my_role,
        is_watching=is_watching,
    )


def _to_ticket_list_item(db: Session, ticket: Ticket, project: Project) -> TicketListItem:
    issue_type = db.get(IssueType, ticket.issue_type_id)
    ticket_status = db.get(TicketStatus, ticket.status_id)
    priority = db.get(TicketPriority, ticket.priority_id) if ticket.priority_id else None
    epic = db.get(Ticket, ticket.epic_id) if ticket.epic_id else None
    if epic is not None and epic.deleted_at is not None:
        epic = None
    return TicketListItem(
        id=ticket.id,
        project_id=ticket.project_id,
        project_key=project.key,
        ticket_key=ticket.ticket_key,
        summary=ticket.summary,
        issue_type=IssueTypeResponse.model_validate(issue_type),
        status=TicketStatusResponse.model_validate(ticket_status),
        priority=TicketPriorityResponse.model_validate(priority) if priority else None,
        assignee_id=ticket.assignee_id,
        assignee_name=_employee_name(db, ticket.assignee_id),
        reporter_id=ticket.reporter_id,
        reporter_name=_employee_name(db, ticket.reporter_id) or "Unknown",
        epic_id=epic.id if epic else None,
        epic_key=epic.ticket_key if epic else None,
        epic_summary=epic.summary if epic else None,
        sprint_id=ticket.sprint_id,
        board_position=ticket.board_position,
        story_points=ticket.story_points,
        due_date=ticket.due_date,
        updated_at=ticket.updated_at,
        labels=_ticket_labels(db, ticket.id),
    )


def _to_relation_summary(ticket: Ticket, status_by_id: dict[int, TicketStatus]) -> TicketRelationSummary:
    ticket_status = status_by_id[ticket.status_id]
    return TicketRelationSummary(
        id=ticket.id, ticket_key=ticket.ticket_key, summary=ticket.summary,
        status_name=ticket_status.name, status_color=ticket_status.color,
    )


def _to_ticket_detail(
    db: Session, ticket: Ticket, project: Project, current_employee: Employee | None, current_user: User | None = None
) -> TicketDetailResponse:
    issue_type = db.get(IssueType, ticket.issue_type_id)
    ticket_status = db.get(TicketStatus, ticket.status_id)
    priority = db.get(TicketPriority, ticket.priority_id) if ticket.priority_id else None

    parent = db.get(Ticket, ticket.parent_id) if ticket.parent_id else None
    if parent is not None and parent.deleted_at is not None:
        parent = None
    epic = db.get(Ticket, ticket.epic_id) if ticket.epic_id else None
    if epic is not None and epic.deleted_at is not None:
        epic = None
    subtasks = list(db.scalars(select(Ticket).where(Ticket.parent_id == ticket.id, Ticket.deleted_at.is_(None))))
    epic_tickets = list(db.scalars(select(Ticket).where(Ticket.epic_id == ticket.id, Ticket.deleted_at.is_(None))))

    related_tickets = [t for t in (parent, epic) if t is not None] + subtasks + epic_tickets
    status_by_id: dict[int, TicketStatus] = {}
    if related_tickets:
        status_ids = {t.status_id for t in related_tickets}
        status_by_id = {s.id: s for s in db.scalars(select(TicketStatus).where(TicketStatus.id.in_(status_ids)))}
    watcher_count = db.scalar(select(func.count(TicketWatcher.id)).where(TicketWatcher.ticket_id == ticket.id)) or 0
    is_watching = False
    if current_employee is not None:
        is_watching = (
            db.scalar(
                select(func.count(TicketWatcher.id)).where(
                    TicketWatcher.ticket_id == ticket.id, TicketWatcher.employee_id == current_employee.id
                )
            )
            or 0
        ) > 0
    my_role = get_project_role(db, project, current_user) if current_user is not None else "viewer"
    return TicketDetailResponse(
        id=ticket.id,
        project_id=ticket.project_id,
        project_key=project.key,
        ticket_key=ticket.ticket_key,
        summary=ticket.summary,
        description=ticket.description,
        issue_type=IssueTypeResponse.model_validate(issue_type),
        status=TicketStatusResponse.model_validate(ticket_status),
        priority=TicketPriorityResponse.model_validate(priority) if priority else None,
        reporter_id=ticket.reporter_id,
        reporter_name=_employee_name(db, ticket.reporter_id) or "Unknown",
        assignee_id=ticket.assignee_id,
        assignee_name=_employee_name(db, ticket.assignee_id),
        parent_id=ticket.parent_id,
        epic_id=ticket.epic_id,
        parent=_to_relation_summary(parent, status_by_id) if parent else None,
        epic=_to_relation_summary(epic, status_by_id) if epic else None,
        subtasks=[_to_relation_summary(t, status_by_id) for t in subtasks],
        epic_tickets=[_to_relation_summary(t, status_by_id) for t in epic_tickets],
        sprint_id=ticket.sprint_id,
        board_position=ticket.board_position,
        story_points=ticket.story_points,
        original_estimate=ticket.original_estimate,
        remaining_estimate=ticket.remaining_estimate,
        time_spent=ticket.time_spent,
        due_date=ticket.due_date,
        resolved_at=ticket.resolved_at,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        is_watching=is_watching,
        watcher_count=watcher_count,
        labels=_ticket_labels(db, ticket.id),
        my_role=my_role,
    )


def _generate_ticket_key(db: Session, project: Project) -> str:
    count = db.scalar(select(func.count(Ticket.id)).where(Ticket.project_id == project.id)) or 0
    return f"{project.key}-{count + 1:03d}"


def _next_board_position(db: Session, status_id: int) -> int:
    max_position = db.scalar(select(func.max(Ticket.board_position)).where(Ticket.status_id == status_id, Ticket.deleted_at.is_(None)))
    return (max_position + 1) if max_position is not None else 0


def _insert_ticket(db: Session, project: Project, status_id: int, board_position: int, **fields) -> Ticket:
    """Allocates a fresh ticket key with retry-on-collision, same as create_ticket's original loop."""
    ticket = None
    for _attempt in range(5):
        ticket_key = _generate_ticket_key(db, project)
        ticket = Ticket(project_id=project.id, ticket_key=ticket_key, status_id=status_id, board_position=board_position, **fields)
        db.add(ticket)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            ticket = None
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Could not allocate a ticket key, please retry")
    db.refresh(ticket)
    return ticket


def _auto_watch(db: Session, ticket_id: int, employee_id: int | None) -> None:
    if employee_id is None:
        return
    exists = db.scalar(
        select(func.count(TicketWatcher.id)).where(
            TicketWatcher.ticket_id == ticket_id, TicketWatcher.employee_id == employee_id
        )
    )
    if not exists:
        db.add(TicketWatcher(ticket_id=ticket_id, employee_id=employee_id))
        db.commit()


def _notify_watchers(
    db: Session, ticket: Ticket, *, exclude_employee_id: int | None, title: str, body: str, link: str
) -> None:
    watcher_employee_ids = db.scalars(
        select(TicketWatcher.employee_id).where(TicketWatcher.ticket_id == ticket.id)
    ).all()
    for employee_id in watcher_employee_ids:
        if employee_id == exclude_employee_id:
            continue
        employee = db.get(Employee, employee_id)
        if employee is None:
            continue
        notify(db, user_id=employee.user_id, category=NotificationCategory.TICKET, title=title, body=body, link=link)


# ================= Projects =================

@projects_router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[ProjectResponse]:
    projects = list(
        db.scalars(select(Project).where(Project.company_id == current_user.company_id).order_by(Project.name))
    )
    return [_to_project_response(db, p, current_user) for p in projects]


@projects_router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    key = payload.key.strip().upper()
    if not key.isalnum():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project key must be alphanumeric")

    existing = db.scalar(
        select(Project).where(Project.company_id == current_user.company_id, Project.key == key)
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Project key '{key}' is already in use")

    _ensure_catalog(db, current_user.company_id)

    project = Project(
        company_id=current_user.company_id,
        key=key,
        name=payload.name,
        description=payload.description,
        lead_id=payload.lead_id,
    )
    db.add(project)
    db.flush()

    for position, (name, category, color) in enumerate(DEFAULT_STATUSES):
        db.add(
            TicketStatus(
                project_id=project.id, name=name, category=category, color=color, position=position,
                is_default=(position == 0),
            )
        )

    creator_employee = db.scalar(
        select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None))
    )
    if creator_employee is not None:
        db.add(ProjectMember(project_id=project.id, employee_id=creator_employee.id, role="admin"))

    db.commit()
    db.refresh(project)
    log_audit(
        db, user_id=current_user.id, action="project_created", entity_type="project",
        entity_id=project.id, ip_address=get_client_ip(request),
    )
    return _to_project_response(db, project, current_user)


@projects_router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> ProjectResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    return _to_project_response(db, project, current_user)


@projects_router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_project")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return _to_project_response(db, project, current_user)


@projects_router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
def list_project_members(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[ProjectMemberResponse]:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    members = list(db.scalars(select(ProjectMember).where(ProjectMember.project_id == project.id)))
    results = []
    for member in members:
        employee = db.get(Employee, member.employee_id)
        user = db.get(User, employee.user_id) if employee else None
        results.append(
            ProjectMemberResponse(
                id=member.id,
                project_id=member.project_id,
                employee_id=member.employee_id,
                employee_name=user.full_name if user else "Unknown",
                employee_code=employee.employee_code if employee else "",
                role=member.role,
            )
        )
    return results


@projects_router.post("/{project_id}/members", response_model=ProjectMemberResponse, status_code=status.HTTP_201_CREATED)
def add_project_member(
    project_id: int,
    payload: ProjectMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectMemberResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_project")
    employee = db.scalar(
        select(Employee).where(
            Employee.id == payload.employee_id, Employee.company_id == current_user.company_id, Employee.deleted_at.is_(None)
        )
    )
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    existing = db.scalar(
        select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.employee_id == employee.id)
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Employee is already a project member")

    member = ProjectMember(project_id=project.id, employee_id=employee.id, role=payload.role)
    db.add(member)
    db.commit()
    db.refresh(member)
    user = db.get(User, employee.user_id)
    return ProjectMemberResponse(
        id=member.id, project_id=member.project_id, employee_id=member.employee_id,
        employee_name=user.full_name if user else "Unknown", employee_code=employee.employee_code, role=member.role,
    )


@projects_router.delete("/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_member(
    project_id: int, member_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_project")
    member = db.scalar(select(ProjectMember).where(ProjectMember.id == member_id, ProjectMember.project_id == project.id))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project member not found")
    db.delete(member)
    db.commit()


@projects_router.put("/{project_id}/members/{member_id}", response_model=ProjectMemberResponse)
def update_project_member_role(
    project_id: int,
    member_id: int,
    payload: ProjectMemberRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectMemberResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_project")
    if payload.role not in PROJECT_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Role must be one of {PROJECT_ROLES}")
    member = db.scalar(select(ProjectMember).where(ProjectMember.id == member_id, ProjectMember.project_id == project.id))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project member not found")
    member.role = payload.role
    db.commit()
    db.refresh(member)
    employee = db.get(Employee, member.employee_id)
    user = db.get(User, employee.user_id) if employee else None
    return ProjectMemberResponse(
        id=member.id, project_id=member.project_id, employee_id=member.employee_id,
        employee_name=user.full_name if user else "Unknown", employee_code=employee.employee_code if employee else "",
        role=member.role,
    )


# ---- Statuses ----

@projects_router.get("/{project_id}/statuses", response_model=list[TicketStatusResponse])
def list_statuses(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[TicketStatusResponse]:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    return list(
        db.scalars(select(TicketStatus).where(TicketStatus.project_id == project.id).order_by(TicketStatus.position))
    )


@projects_router.post("/{project_id}/statuses", response_model=TicketStatusResponse, status_code=status.HTTP_201_CREATED)
def create_status(
    project_id: int,
    payload: TicketStatusCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketStatusResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_project")
    existing = db.scalar(
        select(TicketStatus).where(TicketStatus.project_id == project.id, TicketStatus.name == payload.name)
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A status with this name already exists")
    max_position = db.scalar(select(func.max(TicketStatus.position)).where(TicketStatus.project_id == project.id))
    position = payload.position if payload.position is not None else (max_position + 1 if max_position is not None else 0)
    ticket_status = TicketStatus(
        project_id=project.id, name=payload.name, category=payload.category, color=payload.color, position=position,
        wip_limit=payload.wip_limit,
    )
    db.add(ticket_status)
    db.commit()
    db.refresh(ticket_status)
    return ticket_status


@projects_router.put("/{project_id}/statuses/{status_id}", response_model=TicketStatusResponse)
def update_status(
    project_id: int,
    status_id: int,
    payload: TicketStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketStatusResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_project")
    ticket_status = _get_status_or_404(db, project.id, status_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ticket_status, field, value)
    db.commit()
    db.refresh(ticket_status)
    return ticket_status


@projects_router.delete("/{project_id}/statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_status(
    project_id: int, status_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_project")
    ticket_status = _get_status_or_404(db, project.id, status_id)
    in_use = db.scalar(
        select(func.count(Ticket.id)).where(Ticket.status_id == ticket_status.id, Ticket.deleted_at.is_(None))
    )
    if in_use:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete a status that has tickets")
    db.delete(ticket_status)
    db.commit()


# ---- Sprints ----

@projects_router.get("/{project_id}/sprints", response_model=list[SprintResponse])
def list_sprints(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[SprintResponse]:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    linked_sprint_ids = select(SprintProject.sprint_id).where(SprintProject.project_id == project.id)
    sprints = list(
        db.scalars(
            select(Sprint)
            .where(or_(Sprint.project_id == project.id, Sprint.id.in_(linked_sprint_ids)))
            .order_by(Sprint.id)
        )
    )
    return [_to_sprint_response(db, s) for s in sprints]


@projects_router.post("/{project_id}/sprints", response_model=SprintResponse, status_code=status.HTTP_201_CREATED)
def create_sprint(
    project_id: int,
    payload: SprintCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SprintResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_sprints")
    if payload.start_date and payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_date must be on or after start_date")
    sprint = Sprint(
        project_id=project.id, name=payload.name, goal=payload.goal,
        start_date=payload.start_date, end_date=payload.end_date, status=SprintStatus.FUTURE,
    )
    db.add(sprint)
    db.flush()
    if payload.linked_project_ids:
        _set_sprint_linked_projects(db, sprint, current_user.company_id, payload.linked_project_ids)
    db.commit()
    db.refresh(sprint)
    return _to_sprint_response(db, sprint)


@sprints_router.get("/{sprint_id}", response_model=SprintDetailResponse)
def get_sprint_detail(
    sprint_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> SprintDetailResponse:
    sprint, _owning_project = _get_sprint_with_project_or_404(db, sprint_id, current_user.company_id)
    base = _to_sprint_response(db, sprint)

    project_ids = _sprint_project_ids(db, sprint)
    projects_by_id = {p.id: p for p in db.scalars(select(Project).where(Project.id.in_(project_ids)))}
    tickets = list(db.scalars(select(Ticket).where(Ticket.sprint_id == sprint.id, Ticket.deleted_at.is_(None))))
    done_status_ids = {
        s.id
        for s in db.scalars(
            select(TicketStatus).where(TicketStatus.project_id.in_(project_ids), TicketStatus.category == StatusCategory.DONE)
        )
    }

    tickets_by_project: dict[int, list[Ticket]] = {}
    for t in tickets:
        tickets_by_project.setdefault(t.project_id, []).append(t)
    project_breakdown = [
        SprintProjectBreakdown(
            project_id=pid,
            project_key=projects_by_id[pid].key if pid in projects_by_id else "?",
            project_name=projects_by_id[pid].name if pid in projects_by_id else "Unknown",
            ticket_count=len(pid_tickets),
            total_points=sum(t.story_points or 0 for t in pid_tickets),
            completed_points=sum(t.story_points or 0 for t in pid_tickets if t.status_id in done_status_ids),
        )
        for pid, pid_tickets in sorted(tickets_by_project.items(), key=lambda kv: projects_by_id[kv[0]].key if kv[0] in projects_by_id else "")
    ]

    tickets_by_assignee: dict[int | None, list[Ticket]] = {}
    for t in tickets:
        tickets_by_assignee.setdefault(t.assignee_id, []).append(t)
    assignee_ids = [aid for aid in tickets_by_assignee if aid is not None]
    employee_info: dict[int, tuple[str, str]] = {}
    if assignee_ids:
        for row in db.execute(
            select(Employee.id, Employee.employee_code, User.full_name)
            .join(User, User.id == Employee.user_id)
            .where(Employee.id.in_(assignee_ids))
        ):
            employee_info[row[0]] = (row[1], row[2])
    member_workload = [
        SprintMemberWorkload(
            employee_id=aid,
            employee_name=employee_info[aid][1] if aid in employee_info else "Unassigned",
            employee_code=employee_info[aid][0] if aid in employee_info else None,
            ticket_count=len(aid_tickets),
            total_points=sum(t.story_points or 0 for t in aid_tickets),
            completed_points=sum(t.story_points or 0 for t in aid_tickets if t.status_id in done_status_ids),
        )
        for aid, aid_tickets in tickets_by_assignee.items()
    ]
    member_workload.sort(key=lambda m: (m.employee_id is None, -m.total_points, m.employee_name))

    return SprintDetailResponse(**base.model_dump(), project_breakdown=project_breakdown, member_workload=member_workload)


@sprints_router.put("/{sprint_id}", response_model=SprintResponse)
def update_sprint(
    sprint_id: int,
    payload: SprintUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SprintResponse:
    sprint, project = _get_sprint_with_project_or_404(db, sprint_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_sprints")
    updates = payload.model_dump(exclude_unset=True)
    linked_project_ids = updates.pop("linked_project_ids", None)
    for field, value in updates.items():
        setattr(sprint, field, value)
    if sprint.start_date and sprint.end_date and sprint.end_date < sprint.start_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_date must be on or after start_date")
    if linked_project_ids is not None:
        _set_sprint_linked_projects(db, sprint, current_user.company_id, linked_project_ids)
    db.commit()
    db.refresh(sprint)
    return _to_sprint_response(db, sprint)


@sprints_router.delete("/{sprint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sprint(
    sprint_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    sprint, project = _get_sprint_with_project_or_404(db, sprint_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_sprints")
    if sprint.status != SprintStatus.FUTURE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only a future sprint can be deleted")
    db.delete(sprint)
    db.commit()


@sprints_router.post("/{sprint_id}/start", response_model=SprintResponse)
def start_sprint(
    sprint_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> SprintResponse:
    sprint, project = _get_sprint_with_project_or_404(db, sprint_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_sprints")
    if sprint.status != SprintStatus.FUTURE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only a future sprint can be started")
    existing_active = db.scalar(
        select(func.count(Sprint.id)).where(Sprint.project_id == sprint.project_id, Sprint.status == SprintStatus.ACTIVE)
    )
    if existing_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This project already has an active sprint")
    committed_points = db.scalar(
        select(func.coalesce(func.sum(Ticket.story_points), 0)).where(
            Ticket.sprint_id == sprint.id, Ticket.deleted_at.is_(None)
        )
    )
    sprint.committed_points = committed_points or 0
    sprint.status = SprintStatus.ACTIVE
    db.commit()
    db.refresh(sprint)
    return _to_sprint_response(db, sprint)


@sprints_router.post("/{sprint_id}/complete", response_model=SprintResponse)
def complete_sprint(
    sprint_id: int,
    payload: SprintCompleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SprintResponse:
    sprint, project = _get_sprint_with_project_or_404(db, sprint_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_sprints")
    if sprint.status != SprintStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only an active sprint can be completed")

    done_status_ids = {
        s.id
        for s in db.scalars(
            select(TicketStatus).where(
                TicketStatus.project_id.in_(_sprint_project_ids(db, sprint)), TicketStatus.category == StatusCategory.DONE
            )
        )
    }
    incomplete_tickets = list(
        db.scalars(
            select(Ticket).where(
                Ticket.sprint_id == sprint.id, Ticket.deleted_at.is_(None), ~Ticket.status_id.in_(done_status_ids)
            )
        )
    )
    if payload.incomplete_action == "next_sprint":
        if payload.target_sprint_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_sprint_id is required")
        target_sprint = _get_sprint_or_404(db, sprint.project_id, payload.target_sprint_id)
        for ticket in incomplete_tickets:
            ticket.sprint_id = target_sprint.id
    elif payload.incomplete_action == "backlog":
        for ticket in incomplete_tickets:
            ticket.sprint_id = None
    elif payload.incomplete_action != "keep":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid incomplete_action")

    sprint.status = SprintStatus.COMPLETED
    db.commit()
    db.refresh(sprint)
    return _to_sprint_response(db, sprint)


# ---- Board & Backlog ----

@projects_router.get("/{project_id}/board", response_model=BoardResponse)
def get_board(
    project_id: int,
    sprint_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    statuses = list(
        db.scalars(select(TicketStatus).where(TicketStatus.project_id == project.id).order_by(TicketStatus.position))
    )

    sprint = None
    query = select(Ticket).where(Ticket.project_id == project.id, Ticket.deleted_at.is_(None))
    if sprint_id is not None:
        sprint = _get_sprint_or_404(db, project.id, sprint_id)
        query = query.where(Ticket.sprint_id == sprint.id)
    else:
        linked_sprint_ids = select(SprintProject.sprint_id).where(SprintProject.project_id == project.id)
        active_sprint = db.scalar(
            select(Sprint).where(
                or_(Sprint.project_id == project.id, Sprint.id.in_(linked_sprint_ids)),
                Sprint.status == SprintStatus.ACTIVE,
            )
        )
        if active_sprint is not None:
            sprint = active_sprint
            query = query.where(Ticket.sprint_id == active_sprint.id)
        else:
            query = query.where(Ticket.sprint_id.is_(None))

    tickets = list(db.scalars(query.order_by(Ticket.board_position)))
    return BoardResponse(
        statuses=[TicketStatusResponse.model_validate(s) for s in statuses],
        tickets=[_to_ticket_list_item(db, t, project) for t in tickets],
        sprint=_to_sprint_response(db, sprint) if sprint is not None else None,
    )


@projects_router.get("/{project_id}/backlog", response_model=BacklogResponse)
def get_backlog(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> BacklogResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)

    linked_sprint_ids = select(SprintProject.sprint_id).where(SprintProject.project_id == project.id)
    project_or_linked = or_(Sprint.project_id == project.id, Sprint.id.in_(linked_sprint_ids))
    active_sprint = db.scalar(select(Sprint).where(project_or_linked, Sprint.status == SprintStatus.ACTIVE))
    future_sprints = list(
        db.scalars(
            select(Sprint).where(project_or_linked, Sprint.status == SprintStatus.FUTURE).order_by(Sprint.id)
        )
    )

    active_sprint_tickets = []
    if active_sprint is not None:
        active_sprint_tickets = [
            _to_ticket_list_item(db, t, project)
            for t in db.scalars(
                select(Ticket)
                .where(Ticket.project_id == project.id, Ticket.sprint_id == active_sprint.id, Ticket.deleted_at.is_(None))
                .order_by(Ticket.board_position)
            )
        ]

    future_sprint_tickets: dict[int, list[TicketListItem]] = {}
    for fs in future_sprints:
        future_sprint_tickets[fs.id] = [
            _to_ticket_list_item(db, t, project)
            for t in db.scalars(
                select(Ticket)
                .where(Ticket.project_id == project.id, Ticket.sprint_id == fs.id, Ticket.deleted_at.is_(None))
                .order_by(Ticket.board_position)
            )
        ]

    backlog_tickets = [
        _to_ticket_list_item(db, t, project)
        for t in db.scalars(
            select(Ticket)
            .where(Ticket.project_id == project.id, Ticket.sprint_id.is_(None), Ticket.deleted_at.is_(None))
            .order_by(Ticket.board_position)
        )
    ]

    return BacklogResponse(
        active_sprint=_to_sprint_response(db, active_sprint) if active_sprint is not None else None,
        active_sprint_tickets=active_sprint_tickets,
        future_sprints=[_to_sprint_response(db, s) for s in future_sprints],
        future_sprint_tickets=future_sprint_tickets,
        backlog_tickets=backlog_tickets,
    )


# ================= Catalogs (issue types & priorities) =================

@catalog_router.get("/issue-types", response_model=list[IssueTypeResponse])
def list_issue_types(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[IssueTypeResponse]:
    _ensure_catalog(db, current_user.company_id)
    return list(
        db.scalars(select(IssueType).where(IssueType.company_id == current_user.company_id).order_by(IssueType.position))
    )


@catalog_router.post("/issue-types", response_model=IssueTypeResponse, status_code=status.HTTP_201_CREATED)
def create_issue_type(
    payload: IssueTypeCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> IssueTypeResponse:
    max_position = db.scalar(select(func.max(IssueType.position)).where(IssueType.company_id == current_user.company_id))
    position = payload.position if payload.position is not None else (max_position + 1 if max_position is not None else 0)
    issue_type = IssueType(
        company_id=current_user.company_id, name=payload.name, icon=payload.icon, color=payload.color, position=position,
    )
    db.add(issue_type)
    db.commit()
    db.refresh(issue_type)
    return issue_type


@catalog_router.get("/priorities", response_model=list[TicketPriorityResponse])
def list_priorities(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[TicketPriorityResponse]:
    _ensure_catalog(db, current_user.company_id)
    return list(
        db.scalars(
            select(TicketPriority).where(TicketPriority.company_id == current_user.company_id).order_by(TicketPriority.position)
        )
    )


@catalog_router.post("/priorities", response_model=TicketPriorityResponse, status_code=status.HTTP_201_CREATED)
def create_priority(
    payload: TicketPriorityCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> TicketPriorityResponse:
    max_position = db.scalar(select(func.max(TicketPriority.position)).where(TicketPriority.company_id == current_user.company_id))
    position = payload.position if payload.position is not None else (max_position + 1 if max_position is not None else 0)
    priority = TicketPriority(
        company_id=current_user.company_id, name=payload.name, icon=payload.icon, color=payload.color, position=position,
    )
    db.add(priority)
    db.commit()
    db.refresh(priority)
    return priority


# ================= Tickets =================

@router.get("", response_model=list[TicketListItem])
def list_tickets(
    project_id: int | None = None,
    status_id: int | None = None,
    assignee_id: int | None = None,
    reporter_id: int | None = None,
    priority_id: int | None = None,
    issue_type_id: int | None = None,
    sprint_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TicketListItem]:
    query = (
        select(Ticket)
        .join(Project, Project.id == Ticket.project_id)
        .where(Project.company_id == current_user.company_id, Ticket.deleted_at.is_(None))
    )
    if project_id is not None:
        query = query.where(Ticket.project_id == project_id)
    if status_id is not None:
        query = query.where(Ticket.status_id == status_id)
    if assignee_id is not None:
        query = query.where(Ticket.assignee_id == assignee_id)
    if reporter_id is not None:
        query = query.where(Ticket.reporter_id == reporter_id)
    if priority_id is not None:
        query = query.where(Ticket.priority_id == priority_id)
    if issue_type_id is not None:
        query = query.where(Ticket.issue_type_id == issue_type_id)
    if sprint_id is not None:
        query = query.where(Ticket.sprint_id == sprint_id)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Ticket.summary.ilike(like), Ticket.description.ilike(like), Ticket.ticket_key.ilike(like)))

    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    query = query.order_by(Ticket.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)

    tickets = list(db.scalars(query))
    projects_by_id = {p.id: p for p in db.scalars(select(Project).where(Project.company_id == current_user.company_id))}
    return [_to_ticket_list_item(db, t, projects_by_id[t.project_id]) for t in tickets]


@router.get("/time-report", response_model=TimeReportResponse)
def time_report(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> TimeReportResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "export_reports")

    logs = list(
        db.scalars(
            select(WorkLog).join(Ticket, Ticket.id == WorkLog.ticket_id).where(Ticket.project_id == project.id)
        )
    )
    by_employee: dict[int, dict] = {}
    for log in logs:
        bucket = by_employee.setdefault(log.author_id, {"total": 0, "tickets": {}})
        bucket["total"] += log.minutes_spent
        ticket = db.get(Ticket, log.ticket_id)
        key = ticket.ticket_key if ticket else str(log.ticket_id)
        bucket["tickets"][key] = bucket["tickets"].get(key, 0) + log.minutes_spent

    entries = [
        TimeReportEntry(
            employee_id=eid, employee_name=_employee_name(db, eid) or "Unknown",
            total_minutes=data["total"], ticket_breakdown=data["tickets"],
        )
        for eid, data in by_employee.items()
    ]
    entries.sort(key=lambda e: -e.total_minutes)
    return TimeReportResponse(entries=entries)


# ================= Export =================

@router.get("/export")
def export_tickets(
    project_id: int | None = None,
    status_id: int | None = None,
    assignee_id: int | None = None,
    format: str = "csv",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(Ticket)
        .join(Project, Project.id == Ticket.project_id)
        .where(Project.company_id == current_user.company_id, Ticket.deleted_at.is_(None))
    )
    if project_id is not None:
        query = query.where(Ticket.project_id == project_id)
    if status_id is not None:
        query = query.where(Ticket.status_id == status_id)
    if assignee_id is not None:
        query = query.where(Ticket.assignee_id == assignee_id)

    tickets = list(db.scalars(query.order_by(Ticket.updated_at.desc())))
    projects_by_id = {p.id: p for p in db.scalars(select(Project).where(Project.company_id == current_user.company_id))}
    items = [_to_ticket_list_item(db, t, projects_by_id[t.project_id]) for t in tickets]

    if format == "json":
        return [item.model_dump(mode="json") for item in items]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Key", "Summary", "Type", "Status", "Priority", "Assignee", "Reporter", "Points", "Due Date", "Updated"])
    for item in items:
        writer.writerow([
            item.ticket_key, item.summary, item.issue_type.name, item.status.name,
            item.priority.name if item.priority else "", item.assignee_name or "", item.reporter_name,
            item.story_points if item.story_points is not None else "", item.due_date or "", item.updated_at.isoformat(),
        ])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tickets_export.csv"},
    )


# ================= Global (cross-project) board =================

@router.get("/board", response_model=GlobalBoardResponse)
def get_global_board(
    project_id: list[int] | None = Query(None),
    assignee_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GlobalBoardResponse:
    all_projects = list(
        db.scalars(select(Project).where(Project.company_id == current_user.company_id).order_by(Project.name))
    )
    projects_by_id = {p.id: p for p in all_projects}
    selected_ids = set(project_id) if project_id else set(projects_by_id.keys())

    query = select(Ticket).where(Ticket.project_id.in_(selected_ids), Ticket.deleted_at.is_(None))
    if assignee_id is not None:
        query = query.where(Ticket.assignee_id == assignee_id)
    tickets = list(db.scalars(query.order_by(Ticket.updated_at.desc())))

    return GlobalBoardResponse(
        projects=[BoardProjectSummary(id=p.id, key=p.key, name=p.name) for p in all_projects],
        tickets=[_to_ticket_list_item(db, t, projects_by_id[t.project_id]) for t in tickets],
    )


@router.post("/{ticket_id}/category", response_model=TicketDetailResponse)
def update_ticket_category(
    ticket_id: int,
    payload: TicketCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketDetailResponse:
    """Moves a ticket to the given status category, used by the cross-project global board where
    columns are categories (not literal per-project statuses). Lands on that category's
    lowest-position status within the ticket's own project."""
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    require_permission(db, project, current_user, "transition_ticket")
    actor = _get_own_employee_or_404(db, current_user)

    target_status = db.scalar(
        select(TicketStatus)
        .where(TicketStatus.project_id == project.id, TicketStatus.category == payload.category)
        .order_by(TicketStatus.position)
    )
    if target_status is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Project has no '{payload.category.value}' status")

    old_status = db.get(TicketStatus, ticket.status_id)
    if target_status.id != old_status.id:
        ticket.status_id = target_status.id
        if target_status.category == StatusCategory.DONE and old_status.category != StatusCategory.DONE:
            ticket.resolved_at = utcnow()
        elif old_status.category == StatusCategory.DONE and target_status.category != StatusCategory.DONE:
            ticket.resolved_at = None
        _log_activity(
            db, ticket_id=ticket.id, actor_id=actor.id, action="transitioned",
            field_name="status", old_value=old_status.name, new_value=target_status.name,
        )
        db.commit()
        db.refresh(ticket)
        _notify_watchers(
            db, ticket, exclude_employee_id=actor.id, title=f"{ticket.ticket_key} moved to {target_status.name}",
            body=f"{current_user.full_name} moved {ticket.ticket_key} from {old_status.name} to {target_status.name}.",
            link=f"/tickets/{ticket.id}",
        )
    return _to_ticket_detail(db, ticket, project, actor, current_user)


@router.post("/bulk", response_model=TicketBulkUpdateResponse)
def bulk_update_tickets(
    payload: TicketBulkUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketBulkUpdateResponse:
    actor = _get_own_employee_or_404(db, current_user)
    tickets = list(
        db.scalars(
            select(Ticket)
            .join(Project, Project.id == Ticket.project_id)
            .where(
                Ticket.id.in_(payload.ticket_ids), Project.company_id == current_user.company_id,
                Ticket.deleted_at.is_(None),
            )
        )
    )
    for project_id in {t.project_id for t in tickets}:
        require_permission(db, db.get(Project, project_id), current_user, "edit_any_ticket")

    if payload.delete:
        for ticket in tickets:
            ticket.deleted_at = utcnow()
        db.commit()
        return TicketBulkUpdateResponse(updated_count=len(tickets))

    if payload.status_id is not None:
        for ticket in tickets:
            new_status = _get_status_or_404(db, ticket.project_id, payload.status_id)
            old_status = db.get(TicketStatus, ticket.status_id)
            if new_status.id == old_status.id:
                continue
            ticket.status_id = new_status.id
            if new_status.category == StatusCategory.DONE and old_status.category != StatusCategory.DONE:
                ticket.resolved_at = utcnow()
            elif old_status.category == StatusCategory.DONE and new_status.category != StatusCategory.DONE:
                ticket.resolved_at = None
            _log_activity(
                db, ticket_id=ticket.id, actor_id=actor.id, action="transitioned",
                field_name="status", old_value=old_status.name, new_value=new_status.name,
            )
    if payload.assignee_id is not None:
        for ticket in tickets:
            if ticket.assignee_id == payload.assignee_id:
                continue
            ticket.assignee_id = payload.assignee_id
            _log_activity(db, ticket_id=ticket.id, actor_id=actor.id, action="assigned", new_value=str(payload.assignee_id))
    if payload.sprint_id is not None:
        sprint, _sprint_project = _get_sprint_with_project_or_404(db, payload.sprint_id, current_user.company_id)
        valid_project_ids = _sprint_project_ids(db, sprint)
        for ticket in tickets:
            if ticket.project_id not in valid_project_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Ticket {ticket.ticket_key} does not belong to this sprint's project(s)",
                )
        for ticket in tickets:
            ticket.sprint_id = sprint.id

    db.commit()
    return TicketBulkUpdateResponse(updated_count=len(tickets))


@router.post("", response_model=TicketDetailResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketDetailResponse:
    project = _get_project_or_404(db, payload.project_id, current_user.company_id)
    require_permission(db, project, current_user, "create_ticket")
    reporter = _get_own_employee_or_404(db, current_user)

    issue_type = db.scalar(
        select(IssueType).where(IssueType.id == payload.issue_type_id, IssueType.company_id == current_user.company_id)
    )
    if issue_type is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid issue type")

    if payload.priority_id is not None:
        priority = db.scalar(
            select(TicketPriority).where(
                TicketPriority.id == payload.priority_id, TicketPriority.company_id == current_user.company_id
            )
        )
        if priority is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid priority")

    default_status = db.scalar(
        select(TicketStatus).where(TicketStatus.project_id == project.id, TicketStatus.is_default.is_(True))
    ) or db.scalar(select(TicketStatus).where(TicketStatus.project_id == project.id).order_by(TicketStatus.position))
    if default_status is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project has no statuses configured")

    if payload.parent_id is not None:
        parent = db.scalar(select(Ticket).where(Ticket.id == payload.parent_id, Ticket.project_id == project.id))
        if parent is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent ticket not found in this project")
    if payload.epic_id is not None:
        epic = db.scalar(select(Ticket).where(Ticket.id == payload.epic_id, Ticket.project_id == project.id))
        if epic is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Epic not found in this project")
    if payload.sprint_id is not None:
        _get_sprint_or_404(db, project.id, payload.sprint_id)

    board_position = _next_board_position(db, default_status.id)
    ticket = _insert_ticket(
        db, project, default_status.id, board_position,
        summary=payload.summary,
        description=payload.description,
        issue_type_id=payload.issue_type_id,
        priority_id=payload.priority_id,
        reporter_id=reporter.id,
        assignee_id=payload.assignee_id,
        parent_id=payload.parent_id,
        epic_id=payload.epic_id,
        sprint_id=payload.sprint_id,
        story_points=payload.story_points,
        original_estimate=payload.original_estimate,
        remaining_estimate=payload.original_estimate,
        due_date=payload.due_date,
    )
    _log_activity(db, ticket_id=ticket.id, actor_id=reporter.id, action="created")
    _auto_watch(db, ticket.id, reporter.id)
    _auto_watch(db, ticket.id, payload.assignee_id)

    log_audit(
        db, user_id=current_user.id, action="ticket_created", entity_type="ticket",
        entity_id=ticket.id, ip_address=get_client_ip(request),
    )
    if payload.assignee_id and payload.assignee_id != reporter.id:
        assignee = db.get(Employee, payload.assignee_id)
        if assignee is not None:
            notify(
                db, user_id=assignee.user_id, category=NotificationCategory.TICKET,
                title=f"You were assigned {ticket.ticket_key}",
                body=ticket.summary, link=f"/tickets/{ticket.id}",
            )
    return _to_ticket_detail(db, ticket, project, reporter, current_user)


@router.post("/{ticket_id}/clone", response_model=TicketDetailResponse, status_code=status.HTTP_201_CREATED)
def clone_ticket(
    ticket_id: int,
    payload: TicketCloneRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketDetailResponse:
    source = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, source.project_id)
    require_permission(db, project, current_user, "create_ticket")
    reporter = _get_own_employee_or_404(db, current_user)

    default_status = db.scalar(
        select(TicketStatus).where(TicketStatus.project_id == project.id, TicketStatus.is_default.is_(True))
    ) or db.scalar(select(TicketStatus).where(TicketStatus.project_id == project.id).order_by(TicketStatus.position))
    if default_status is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project has no statuses configured")

    board_position = _next_board_position(db, default_status.id)
    clone = _insert_ticket(
        db, project, default_status.id, board_position,
        summary=payload.summary or f"Copy of {source.summary}",
        description=source.description,
        issue_type_id=source.issue_type_id,
        priority_id=source.priority_id,
        reporter_id=reporter.id,
        assignee_id=source.assignee_id,
        parent_id=source.parent_id if payload.include_parent_epic else None,
        epic_id=source.epic_id if payload.include_parent_epic else None,
        sprint_id=None,
        story_points=source.story_points,
        original_estimate=source.original_estimate,
        remaining_estimate=source.original_estimate,
        due_date=source.due_date,
    )
    _log_activity(
        db, ticket_id=clone.id, actor_id=reporter.id, action="created",
        field_name="cloned_from", new_value=source.ticket_key,
    )
    _auto_watch(db, clone.id, reporter.id)
    _auto_watch(db, clone.id, clone.assignee_id)

    label_ids = db.scalars(select(TicketLabel.label_id).where(TicketLabel.ticket_id == source.id)).all()
    for label_id in label_ids:
        db.add(TicketLabel(ticket_id=clone.id, label_id=label_id))
    if label_ids:
        db.commit()

    if payload.include_subtasks:
        subtasks = list(
            db.scalars(select(Ticket).where(Ticket.parent_id == source.id, Ticket.deleted_at.is_(None)))
        )
        for sub in subtasks:
            sub_position = _next_board_position(db, default_status.id)
            sub_clone = _insert_ticket(
                db, project, default_status.id, sub_position,
                summary=sub.summary,
                description=sub.description,
                issue_type_id=sub.issue_type_id,
                priority_id=sub.priority_id,
                reporter_id=reporter.id,
                assignee_id=sub.assignee_id,
                parent_id=clone.id,
                epic_id=None,
                sprint_id=None,
                story_points=sub.story_points,
                original_estimate=sub.original_estimate,
                remaining_estimate=sub.original_estimate,
                due_date=sub.due_date,
            )
            _log_activity(
                db, ticket_id=sub_clone.id, actor_id=reporter.id, action="created",
                field_name="cloned_from", new_value=sub.ticket_key,
            )
            _auto_watch(db, sub_clone.id, reporter.id)
            _auto_watch(db, sub_clone.id, sub_clone.assignee_id)

    if payload.include_comments:
        comments = list(
            db.scalars(
                select(TicketComment)
                .where(TicketComment.ticket_id == source.id, TicketComment.deleted_at.is_(None))
                .order_by(TicketComment.created_at)
            )
        )
        for comment in comments:
            db.add(TicketComment(ticket_id=clone.id, author_id=comment.author_id, body=comment.body, is_internal=comment.is_internal))
        if comments:
            db.commit()

    if payload.include_attachments:
        attachments = list(db.scalars(select(TicketAttachment).where(TicketAttachment.ticket_id == source.id)))
        copied_any = False
        for attachment in attachments:
            new_path = copy_ticket_attachment(current_user.company_id, clone.id, attachment.file_path, attachment.file_name)
            if new_path is None:
                continue
            db.add(
                TicketAttachment(
                    ticket_id=clone.id, uploader_id=reporter.id, file_path=new_path,
                    file_name=attachment.file_name, file_size=attachment.file_size, mime_type=attachment.mime_type,
                )
            )
            copied_any = True
        if copied_any:
            db.commit()

    log_audit(
        db, user_id=current_user.id, action="ticket_cloned", entity_type="ticket",
        entity_id=clone.id, ip_address=get_client_ip(request),
    )
    if clone.assignee_id and clone.assignee_id != reporter.id:
        assignee = db.get(Employee, clone.assignee_id)
        if assignee is not None:
            notify(
                db, user_id=assignee.user_id, category=NotificationCategory.TICKET,
                title=f"You were assigned {clone.ticket_key}",
                body=clone.summary, link=f"/tickets/{clone.id}",
            )
    db.refresh(clone)
    return _to_ticket_detail(db, clone, project, reporter, current_user)


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
def get_ticket(
    ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> TicketDetailResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    current_employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    return _to_ticket_detail(db, ticket, project, current_employee, current_user)


@router.put("/{ticket_id}", response_model=TicketDetailResponse)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketDetailResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    actor = _get_own_employee_or_404(db, current_user)
    is_own = actor.id in (ticket.reporter_id, ticket.assignee_id)
    require_permission(db, project, current_user, "edit_own_ticket" if is_own else "edit_any_ticket")

    if payload.parent_id is not None:
        if payload.parent_id == ticket.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A ticket cannot be its own parent")
        parent = db.scalar(select(Ticket).where(Ticket.id == payload.parent_id, Ticket.project_id == project.id))
        if parent is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent ticket not found in this project")
    if payload.epic_id is not None:
        if payload.epic_id == ticket.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A ticket cannot be its own epic")
        epic = db.scalar(select(Ticket).where(Ticket.id == payload.epic_id, Ticket.project_id == project.id))
        if epic is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Epic not found in this project")

    updates = payload.model_dump(exclude_unset=True)
    old_assignee_id = ticket.assignee_id
    for field, value in updates.items():
        old_value = getattr(ticket, field)
        if old_value == value:
            continue
        setattr(ticket, field, value)
        _log_activity(
            db, ticket_id=ticket.id, actor_id=actor.id, action="updated", field_name=field,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(value) if value is not None else None,
        )
    db.commit()
    db.refresh(ticket)

    if "assignee_id" in updates and ticket.assignee_id != old_assignee_id:
        _auto_watch(db, ticket.id, ticket.assignee_id)
        if ticket.assignee_id:
            assignee = db.get(Employee, ticket.assignee_id)
            if assignee is not None:
                notify(
                    db, user_id=assignee.user_id, category=NotificationCategory.TICKET,
                    title=f"You were assigned {ticket.ticket_key}",
                    body=ticket.summary, link=f"/tickets/{ticket.id}",
                )
    if updates:
        _notify_watchers(
            db, ticket, exclude_employee_id=actor.id, title=f"{ticket.ticket_key} was updated",
            body=f"{current_user.full_name} updated {ticket.ticket_key}.", link=f"/tickets/{ticket.id}",
        )
    return _to_ticket_detail(db, ticket, project, actor, current_user)


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket(
    ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    require_permission(db, project, current_user, "delete_ticket")
    ticket.deleted_at = utcnow()
    db.commit()


@router.post("/{ticket_id}/transition", response_model=TicketDetailResponse)
def transition_ticket(
    ticket_id: int,
    payload: TicketTransitionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketDetailResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    require_permission(db, project, current_user, "transition_ticket")
    actor = _get_own_employee_or_404(db, current_user)

    new_status = _get_status_or_404(db, project.id, payload.status_id)
    old_status = db.get(TicketStatus, ticket.status_id)
    if new_status.id == old_status.id:
        return _to_ticket_detail(db, ticket, project, actor, current_user)

    ticket.status_id = new_status.id
    if new_status.category == StatusCategory.DONE and old_status.category != StatusCategory.DONE:
        ticket.resolved_at = utcnow()
    elif old_status.category == StatusCategory.DONE and new_status.category != StatusCategory.DONE:
        ticket.resolved_at = None

    _log_activity(
        db, ticket_id=ticket.id, actor_id=actor.id, action="transitioned",
        field_name="status", old_value=old_status.name, new_value=new_status.name,
    )
    db.commit()
    db.refresh(ticket)

    _notify_watchers(
        db, ticket, exclude_employee_id=actor.id, title=f"{ticket.ticket_key} moved to {new_status.name}",
        body=f"{current_user.full_name} moved {ticket.ticket_key} from {old_status.name} to {new_status.name}.",
        link=f"/tickets/{ticket.id}",
    )
    return _to_ticket_detail(db, ticket, project, actor, current_user)


@router.post("/{ticket_id}/position", response_model=TicketDetailResponse)
def update_ticket_position(
    ticket_id: int,
    payload: TicketPositionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketDetailResponse:
    """Reorders a card within a column, moving it between columns (a status transition) if needed."""
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    require_permission(db, project, current_user, "transition_ticket")
    actor = _get_own_employee_or_404(db, current_user)

    new_status = _get_status_or_404(db, project.id, payload.status_id)
    old_status = db.get(TicketStatus, ticket.status_id)
    status_changed = new_status.id != old_status.id

    if status_changed:
        ticket.status_id = new_status.id
        if new_status.category == StatusCategory.DONE and old_status.category != StatusCategory.DONE:
            ticket.resolved_at = utcnow()
        elif old_status.category == StatusCategory.DONE and new_status.category != StatusCategory.DONE:
            ticket.resolved_at = None
        _log_activity(
            db, ticket_id=ticket.id, actor_id=actor.id, action="transitioned",
            field_name="status", old_value=old_status.name, new_value=new_status.name,
        )

    # Re-sequence the destination column so the moved card lands at the requested index.
    siblings = list(
        db.scalars(
            select(Ticket)
            .where(Ticket.status_id == new_status.id, Ticket.deleted_at.is_(None), Ticket.id != ticket.id)
            .order_by(Ticket.board_position)
        )
    )
    target_index = max(0, min(payload.position, len(siblings)))
    siblings.insert(target_index, ticket)
    for index, sibling in enumerate(siblings):
        sibling.board_position = index

    db.commit()
    db.refresh(ticket)
    if status_changed:
        _notify_watchers(
            db, ticket, exclude_employee_id=actor.id, title=f"{ticket.ticket_key} moved to {new_status.name}",
            body=f"{current_user.full_name} moved {ticket.ticket_key} from {old_status.name} to {new_status.name}.",
            link=f"/tickets/{ticket.id}",
        )
    return _to_ticket_detail(db, ticket, project, actor, current_user)


@router.post("/{ticket_id}/sprint", response_model=TicketDetailResponse)
def assign_ticket_sprint(
    ticket_id: int,
    payload: TicketSprintAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketDetailResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    require_permission(db, project, current_user, "manage_sprints")
    actor = _get_own_employee_or_404(db, current_user)

    old_sprint_id = ticket.sprint_id
    if payload.sprint_id is not None:
        _get_sprint_or_404(db, project.id, payload.sprint_id)
    if payload.sprint_id != old_sprint_id:
        ticket.sprint_id = payload.sprint_id
        _log_activity(
            db, ticket_id=ticket.id, actor_id=actor.id, action="updated", field_name="sprint_id",
            old_value=str(old_sprint_id) if old_sprint_id is not None else None,
            new_value=str(payload.sprint_id) if payload.sprint_id is not None else None,
        )
        db.commit()
        db.refresh(ticket)
    return _to_ticket_detail(db, ticket, project, actor, current_user)


@router.post("/{ticket_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
def watch_ticket(
    ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    employee = _get_own_employee_or_404(db, current_user)
    _auto_watch(db, ticket.id, employee.id)


@router.delete("/{ticket_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
def unwatch_ticket(
    ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    employee = _get_own_employee_or_404(db, current_user)
    watcher = db.scalar(
        select(TicketWatcher).where(TicketWatcher.ticket_id == ticket.id, TicketWatcher.employee_id == employee.id)
    )
    if watcher is not None:
        db.delete(watcher)
        db.commit()


# ---- Comments ----

@router.get("/{ticket_id}/comments", response_model=list[TicketCommentResponse])
def list_comments(
    ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[TicketCommentResponse]:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    comments = list(
        db.scalars(
            select(TicketComment)
            .where(TicketComment.ticket_id == ticket.id, TicketComment.deleted_at.is_(None))
            .order_by(TicketComment.created_at)
        )
    )
    return [
        TicketCommentResponse(
            id=c.id, ticket_id=c.ticket_id, author_id=c.author_id, author_name=_employee_name(db, c.author_id) or "Unknown",
            body=c.body, is_internal=c.is_internal, created_at=c.created_at, updated_at=c.updated_at,
        )
        for c in comments
    ]


@router.post("/{ticket_id}/comments", response_model=TicketCommentResponse, status_code=status.HTTP_201_CREATED)
def add_comment(
    ticket_id: int,
    payload: TicketCommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketCommentResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    require_permission(db, db.get(Project, ticket.project_id), current_user, "comment")
    author = _get_own_employee_or_404(db, current_user)

    comment = TicketComment(ticket_id=ticket.id, author_id=author.id, body=payload.body, is_internal=payload.is_internal)
    db.add(comment)
    db.commit()
    db.refresh(comment)

    _log_activity(db, ticket_id=ticket.id, actor_id=author.id, action="commented", new_value=str(comment.id))
    _auto_watch(db, ticket.id, author.id)
    _notify_watchers(
        db, ticket, exclude_employee_id=author.id, title=f"New comment on {ticket.ticket_key}",
        body=f"{current_user.full_name} commented: {payload.body[:120]}", link=f"/tickets/{ticket.id}",
    )
    return TicketCommentResponse(
        id=comment.id, ticket_id=comment.ticket_id, author_id=comment.author_id,
        author_name=current_user.full_name, body=comment.body, is_internal=comment.is_internal,
        created_at=comment.created_at, updated_at=comment.updated_at,
    )


@router.put("/{ticket_id}/comments/{comment_id}", response_model=TicketCommentResponse)
def update_comment(
    ticket_id: int,
    comment_id: int,
    payload: TicketCommentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketCommentResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    author = _get_own_employee_or_404(db, current_user)
    comment = db.scalar(
        select(TicketComment).where(
            TicketComment.id == comment_id, TicketComment.ticket_id == ticket.id, TicketComment.deleted_at.is_(None)
        )
    )
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if comment.author_id != author.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own comments")
    age_minutes = (utcnow() - comment.created_at).total_seconds() / 60
    if age_minutes > COMMENT_EDIT_WINDOW_MINUTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Comment edit window has expired")

    comment.body = payload.body
    db.commit()
    db.refresh(comment)
    return TicketCommentResponse(
        id=comment.id, ticket_id=comment.ticket_id, author_id=comment.author_id,
        author_name=current_user.full_name, body=comment.body, is_internal=comment.is_internal,
        created_at=comment.created_at, updated_at=comment.updated_at,
    )


@router.delete("/{ticket_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    ticket_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    author = _get_own_employee_or_404(db, current_user)
    comment = db.scalar(
        select(TicketComment).where(
            TicketComment.id == comment_id, TicketComment.ticket_id == ticket.id, TicketComment.deleted_at.is_(None)
        )
    )
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if comment.author_id != author.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own comments")
    comment.deleted_at = utcnow()
    db.commit()


# ---- Attachments ----

@router.get("/{ticket_id}/attachments", response_model=list[TicketAttachmentResponse])
def list_attachments(
    ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[TicketAttachmentResponse]:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    attachments = list(
        db.scalars(select(TicketAttachment).where(TicketAttachment.ticket_id == ticket.id).order_by(TicketAttachment.created_at))
    )
    return [
        TicketAttachmentResponse(
            id=a.id, ticket_id=a.ticket_id, uploader_id=a.uploader_id, uploader_name=_employee_name(db, a.uploader_id) or "Unknown",
            file_name=a.file_name, file_size=a.file_size, mime_type=a.mime_type, created_at=a.created_at,
        )
        for a in attachments
    ]


@router.post("/{ticket_id}/attachments", response_model=TicketAttachmentResponse, status_code=status.HTTP_201_CREATED)
def upload_attachment(
    ticket_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketAttachmentResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    require_permission(db, db.get(Project, ticket.project_id), current_user, "comment")
    uploader = _get_own_employee_or_404(db, current_user)

    saved = save_ticket_attachment(current_user.company_id, ticket.id, file)
    attachment = TicketAttachment(
        ticket_id=ticket.id, uploader_id=uploader.id, file_path=saved.file_path,
        file_name=saved.file_name, file_size=saved.file_size, mime_type=saved.mime_type,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    _log_activity(db, ticket_id=ticket.id, actor_id=uploader.id, action="attachment_added", new_value=saved.file_name)
    return TicketAttachmentResponse(
        id=attachment.id, ticket_id=attachment.ticket_id, uploader_id=attachment.uploader_id,
        uploader_name=current_user.full_name, file_name=attachment.file_name, file_size=attachment.file_size,
        mime_type=attachment.mime_type, created_at=attachment.created_at,
    )


@router.get("/{ticket_id}/attachments/{attachment_id}/download")
def download_attachment(
    ticket_id: int, attachment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> FileResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    attachment = db.scalar(
        select(TicketAttachment).where(TicketAttachment.id == attachment_id, TicketAttachment.ticket_id == ticket.id)
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return FileResponse(attachment.file_path, filename=attachment.file_name, media_type=attachment.mime_type)


@router.delete("/{ticket_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(
    ticket_id: int, attachment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    actor = _get_own_employee_or_404(db, current_user)
    attachment = db.scalar(
        select(TicketAttachment).where(TicketAttachment.id == attachment_id, TicketAttachment.ticket_id == ticket.id)
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if attachment.uploader_id != actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the uploader can delete this attachment")

    delete_file_if_exists(attachment.file_path)
    file_name = attachment.file_name
    db.delete(attachment)
    _log_activity(db, ticket_id=ticket.id, actor_id=actor.id, action="attachment_deleted", old_value=file_name)
    db.commit()


# ---- Activity ----

@router.get("/{ticket_id}/activities", response_model=list[TicketActivityResponse])
def list_activities(
    ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[TicketActivityResponse]:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    activities = list(
        db.scalars(select(TicketActivity).where(TicketActivity.ticket_id == ticket.id).order_by(TicketActivity.created_at))
    )
    return [
        TicketActivityResponse(
            id=a.id, ticket_id=a.ticket_id, actor_id=a.actor_id, actor_name=_employee_name(db, a.actor_id) or "Unknown",
            action=a.action, field_name=a.field_name, old_value=a.old_value, new_value=a.new_value, created_at=a.created_at,
        )
        for a in activities
    ]


# ================= Labels =================

@projects_router.get("/{project_id}/labels", response_model=list[LabelResponse])
def list_labels(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[LabelResponse]:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    return list(db.scalars(select(Label).where(Label.project_id == project.id).order_by(Label.name)))


@projects_router.post("/{project_id}/labels", response_model=LabelResponse, status_code=status.HTTP_201_CREATED)
def create_label(
    project_id: int, payload: LabelCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> LabelResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_sprints")
    existing = db.scalar(select(Label).where(Label.project_id == project.id, Label.name == payload.name))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A label with this name already exists")
    label = Label(project_id=project.id, name=payload.name, color=payload.color)
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


@projects_router.delete("/{project_id}/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(
    project_id: int, label_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    require_permission(db, project, current_user, "manage_sprints")
    label = db.scalar(select(Label).where(Label.id == label_id, Label.project_id == project.id))
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label not found")
    db.execute(TicketLabel.__table__.delete().where(TicketLabel.label_id == label.id))
    db.delete(label)
    db.commit()


@router.post("/{ticket_id}/labels", response_model=TicketDetailResponse)
def add_ticket_label(
    ticket_id: int, payload: TicketLabelAssign, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> TicketDetailResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    require_permission(db, project, current_user, "transition_ticket")
    actor = _get_own_employee_or_404(db, current_user)

    label = db.scalar(select(Label).where(Label.id == payload.label_id, Label.project_id == project.id))
    if label is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid label")
    existing = db.scalar(select(TicketLabel).where(TicketLabel.ticket_id == ticket.id, TicketLabel.label_id == label.id))
    if existing is None:
        db.add(TicketLabel(ticket_id=ticket.id, label_id=label.id))
        db.commit()
    return _to_ticket_detail(db, ticket, project, actor, current_user)


@router.delete("/{ticket_id}/labels/{label_id}", response_model=TicketDetailResponse)
def remove_ticket_label(
    ticket_id: int, label_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> TicketDetailResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    require_permission(db, project, current_user, "transition_ticket")
    actor = _get_own_employee_or_404(db, current_user)

    link = db.scalar(select(TicketLabel).where(TicketLabel.ticket_id == ticket.id, TicketLabel.label_id == label_id))
    if link is not None:
        db.delete(link)
        db.commit()
    return _to_ticket_detail(db, ticket, project, actor, current_user)


# ================= Project watching =================

@projects_router.post("/{project_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
def watch_project(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    employee = _get_own_employee_or_404(db, current_user)
    exists = db.scalar(
        select(func.count(ProjectWatcher.id)).where(
            ProjectWatcher.project_id == project.id, ProjectWatcher.employee_id == employee.id
        )
    )
    if not exists:
        db.add(ProjectWatcher(project_id=project.id, employee_id=employee.id))
        db.commit()


@projects_router.delete("/{project_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
def unwatch_project(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    employee = _get_own_employee_or_404(db, current_user)
    watcher = db.scalar(
        select(ProjectWatcher).where(ProjectWatcher.project_id == project.id, ProjectWatcher.employee_id == employee.id)
    )
    if watcher is not None:
        db.delete(watcher)
        db.commit()


# ================= Time tracking =================

@router.get("/{ticket_id}/worklogs", response_model=list[WorkLogResponse])
def list_worklogs(
    ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[WorkLogResponse]:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    logs = list(db.scalars(select(WorkLog).where(WorkLog.ticket_id == ticket.id).order_by(WorkLog.log_date.desc())))
    return [
        WorkLogResponse(
            id=w.id, ticket_id=w.ticket_id, author_id=w.author_id, author_name=_employee_name(db, w.author_id) or "Unknown",
            minutes_spent=w.minutes_spent, log_date=w.log_date, description=w.description, created_at=w.created_at,
        )
        for w in logs
    ]


@router.post("/{ticket_id}/worklogs", response_model=TicketDetailResponse, status_code=status.HTTP_201_CREATED)
def add_worklog(
    ticket_id: int, payload: WorkLogCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> TicketDetailResponse:
    ticket = _get_ticket_or_404(db, ticket_id, current_user.company_id)
    project = db.get(Project, ticket.project_id)
    require_permission(db, project, current_user, "log_work")
    author = _get_own_employee_or_404(db, current_user)

    if payload.minutes_spent <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="minutes_spent must be positive")

    db.add(
        WorkLog(
            ticket_id=ticket.id, author_id=author.id, minutes_spent=payload.minutes_spent,
            log_date=payload.log_date, description=payload.description,
        )
    )
    ticket.time_spent += payload.minutes_spent
    if ticket.remaining_estimate is not None:
        ticket.remaining_estimate = max(ticket.remaining_estimate - payload.minutes_spent, 0)
    db.commit()
    db.refresh(ticket)

    _log_activity(
        db, ticket_id=ticket.id, actor_id=author.id, action="logged_work", new_value=f"{payload.minutes_spent}m",
    )
    return _to_ticket_detail(db, ticket, project, author, current_user)


