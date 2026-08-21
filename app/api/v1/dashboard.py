import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.employee import Employee
from app.models.mixins import utcnow
from app.models.project import Project, ProjectMember, Sprint, SprintProject, SprintStatus, StatusCategory, TicketStatus
from app.models.ticket import IssueType, Ticket, TicketActivity, TicketPriority
from app.models.user import User
from app.schemas.ticket import (
    BurndownPoint,
    BurndownResponse,
    CategoryDistributionSlice,
    DashboardKpis,
    DashboardResponse,
    GlobalDashboardResponse,
    IssueTypeResponse,
    KpiCard,
    MyOpenTicket,
    ProjectBreakdownEntry,
    RecentActivityItem,
    ResolutionBucket,
    SprintProgress,
    SprintReportResponse,
    StatusDistributionSlice,
    TicketListItem,
    TicketPriorityResponse,
    TicketStatusResponse,
    TrendPoint,
    VelocityEntry,
    VelocityResponse,
    WorkloadEntry,
    WorkloadReportResponse,
)

router = APIRouter(tags=["dashboard"])

RESOLUTION_BUCKETS = [
    ("0-1 day", 0, 1),
    ("1-3 days", 1, 3),
    ("3-7 days", 3, 7),
    ("7-14 days", 7, 14),
    ("14+ days", 14, None),
]


# ---- Helpers ----

def _get_project_or_404(db: Session, project_id: int, company_id: int | None) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.company_id == company_id))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _sprint_project_ids(db: Session, sprint: Sprint) -> set[int]:
    linked = db.scalars(select(SprintProject.project_id).where(SprintProject.sprint_id == sprint.id))
    return {sprint.project_id, *linked}


def _get_sprint_or_404(db: Session, project_id: int, sprint_id: int) -> Sprint:
    sprint = db.get(Sprint, sprint_id)
    if sprint is None or project_id not in _sprint_project_ids(db, sprint):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")
    return sprint


def _employee_name(db: Session, employee_id: int | None) -> str | None:
    if employee_id is None:
        return None
    row = db.execute(
        select(User.full_name).join(Employee, Employee.user_id == User.id).where(Employee.id == employee_id)
    ).first()
    return row[0] if row else None


def _to_ticket_list_item(db: Session, ticket: Ticket, project: Project, status_by_id: dict, type_by_id: dict, priority_by_id: dict) -> TicketListItem:
    ticket_status = status_by_id[ticket.status_id]
    issue_type = type_by_id[ticket.issue_type_id]
    priority = priority_by_id.get(ticket.priority_id) if ticket.priority_id else None
    return TicketListItem(
        id=ticket.id, project_id=ticket.project_id, project_key=project.key, ticket_key=ticket.ticket_key,
        summary=ticket.summary, issue_type=IssueTypeResponse.model_validate(issue_type),
        status=TicketStatusResponse.model_validate(ticket_status),
        priority=TicketPriorityResponse.model_validate(priority) if priority else None,
        assignee_id=ticket.assignee_id, assignee_name=_employee_name(db, ticket.assignee_id),
        reporter_id=ticket.reporter_id, reporter_name=_employee_name(db, ticket.reporter_id) or "Unknown",
        sprint_id=ticket.sprint_id, board_position=ticket.board_position, story_points=ticket.story_points,
        due_date=ticket.due_date, updated_at=ticket.updated_at,
    )


def _category_snapshot(
    all_tickets: list[Ticket], activities: list[TicketActivity], status_category_by_name: dict[str, StatusCategory],
    default_status_name_by_project: dict[int, str], asof: datetime,
) -> dict[int, StatusCategory]:
    """Reconstructs each ticket's status category as of a past moment, using the transition
    activity log (falling back to its project's default/initial status for tickets with no
    recorded transition yet). Renamed or deleted statuses since `asof` are not accounted for."""
    last_status_name: dict[int, tuple[datetime, str]] = {}
    for activity in activities:
        if activity.action != "transitioned" or activity.created_at > asof or not activity.new_value:
            continue
        current = last_status_name.get(activity.ticket_id)
        if current is None or activity.created_at > current[0]:
            last_status_name[activity.ticket_id] = (activity.created_at, activity.new_value)

    snapshot: dict[int, StatusCategory] = {}
    for ticket in all_tickets:
        if ticket.created_at > asof:
            continue
        if ticket.deleted_at is not None and ticket.deleted_at <= asof:
            continue
        if ticket.id in last_status_name:
            name = last_status_name[ticket.id][1]
        else:
            name = default_status_name_by_project.get(ticket.project_id)
            if name is None:
                continue
        category = status_category_by_name.get(name)
        if category is not None:
            snapshot[ticket.id] = category
    return snapshot


# ---- Dashboard ----

@router.get("/dashboard/{project_id}", response_model=DashboardResponse)
def get_dashboard(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> DashboardResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    now = utcnow()
    today = now.date()
    week_ago = now - timedelta(days=7)

    statuses = list(db.scalars(select(TicketStatus).where(TicketStatus.project_id == project.id)))
    status_by_id = {s.id: s for s in statuses}
    status_category_by_name = {s.name: s.category for s in statuses}
    default_status = next((s for s in statuses if s.is_default), statuses[0] if statuses else None)

    all_tickets = list(db.scalars(select(Ticket).where(Ticket.project_id == project.id)))
    live_tickets = [t for t in all_tickets if t.deleted_at is None]

    # ---- KPIs ----
    open_count = sum(1 for t in live_tickets if status_by_id[t.status_id].category != StatusCategory.DONE)
    in_progress_count = sum(1 for t in live_tickets if status_by_id[t.status_id].category == StatusCategory.INPROGRESS)
    completed_this_week = sum(1 for t in live_tickets if t.resolved_at and t.resolved_at >= week_ago)
    completed_prior_week = sum(
        1 for t in live_tickets if t.resolved_at and week_ago - timedelta(days=7) <= t.resolved_at < week_ago
    )
    overdue_count = sum(
        1 for t in live_tickets
        if t.due_date and t.due_date < today and status_by_id[t.status_id].category != StatusCategory.DONE
    )

    activities = list(
        db.scalars(
            select(TicketActivity)
            .join(Ticket, Ticket.id == TicketActivity.ticket_id)
            .where(Ticket.project_id == project.id, TicketActivity.action == "transitioned")
        )
    )
    snapshot = (
        _category_snapshot(all_tickets, activities, status_category_by_name, {project.id: default_status.name}, week_ago)
        if default_status else {}
    )
    open_week_ago = sum(1 for cat in snapshot.values() if cat != StatusCategory.DONE)
    in_progress_week_ago = sum(1 for cat in snapshot.values() if cat == StatusCategory.INPROGRESS)
    overdue_week_ago = sum(
        1 for t in all_tickets
        if t.id in snapshot and snapshot[t.id] != StatusCategory.DONE and t.due_date and t.due_date < week_ago.date()
    )

    def _trend(current: int, previous: int) -> float | None:
        if previous == 0:
            return None if current == 0 else 100.0
        return round((current - previous) / previous * 100, 1)

    kpis = DashboardKpis(
        open=KpiCard(value=open_count, trend_pct=_trend(open_count, open_week_ago)),
        in_progress=KpiCard(value=in_progress_count, trend_pct=_trend(in_progress_count, in_progress_week_ago)),
        completed_this_week=KpiCard(value=completed_this_week, trend_pct=_trend(completed_this_week, completed_prior_week)),
        overdue=KpiCard(value=overdue_count, trend_pct=_trend(overdue_count, overdue_week_ago)),
    )

    # ---- Status distribution ----
    counts_by_status: dict[int, int] = defaultdict(int)
    for t in live_tickets:
        counts_by_status[t.status_id] += 1
    status_distribution = [
        StatusDistributionSlice(status_id=s.id, name=s.name, color=s.color, count=counts_by_status.get(s.id, 0))
        for s in sorted(statuses, key=lambda s: s.position)
    ]

    # ---- Workload distribution ----
    members = list(
        db.scalars(
            select(ProjectMember).where(ProjectMember.project_id == project.id)
        )
    )
    member_ids = {m.employee_id for m in members} | {t.assignee_id for t in live_tickets if t.assignee_id}
    workload_by_employee: dict[int, dict] = {
        eid: {"open": 0, "in_progress": 0, "overdue": 0, "points": 0} for eid in member_ids
    }
    unassigned = {"open": 0, "in_progress": 0, "overdue": 0, "points": 0}
    for t in live_tickets:
        cat = status_by_id[t.status_id].category
        if cat == StatusCategory.DONE:
            continue
        bucket = workload_by_employee[t.assignee_id] if t.assignee_id else unassigned
        bucket["open"] += 1
        if cat == StatusCategory.INPROGRESS:
            bucket["in_progress"] += 1
        if t.due_date and t.due_date < today:
            bucket["overdue"] += 1
        bucket["points"] += t.story_points or 0

    workload_distribution = [
        WorkloadEntry(
            employee_id=eid, employee_name=_employee_name(db, eid) or "Unknown",
            open_count=data["open"], in_progress_count=data["in_progress"],
            overdue_count=data["overdue"], total_points=data["points"],
        )
        for eid, data in workload_by_employee.items()
    ]
    workload_distribution.sort(key=lambda w: -w.open_count)
    if unassigned["open"]:
        workload_distribution.append(
            WorkloadEntry(
                employee_id=None, employee_name="Unassigned", open_count=unassigned["open"],
                in_progress_count=unassigned["in_progress"], overdue_count=unassigned["overdue"],
                total_points=unassigned["points"],
            )
        )

    # ---- Creation trend (last 30 days) ----
    thirty_days_ago = today - timedelta(days=29)
    counts_by_day: dict[date, int] = defaultdict(int)
    for t in all_tickets:
        d = t.created_at.date()
        if d >= thirty_days_ago:
            counts_by_day[d] += 1
    creation_trend = [
        TrendPoint(date=thirty_days_ago + timedelta(days=i), count=counts_by_day.get(thirty_days_ago + timedelta(days=i), 0))
        for i in range(30)
    ]

    # ---- Resolution time buckets ----
    bucket_counts = [0] * len(RESOLUTION_BUCKETS)
    for t in live_tickets:
        if not t.resolved_at:
            continue
        days_to_resolve = (t.resolved_at - t.created_at).total_seconds() / 86400
        for i, (_, lo, hi) in enumerate(RESOLUTION_BUCKETS):
            if days_to_resolve >= lo and (hi is None or days_to_resolve < hi):
                bucket_counts[i] += 1
                break
    resolution_time_buckets = [
        ResolutionBucket(label=RESOLUTION_BUCKETS[i][0], count=bucket_counts[i]) for i in range(len(RESOLUTION_BUCKETS))
    ]

    # ---- My open tickets ----
    my_open_tickets: list[MyOpenTicket] = []
    current_employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if current_employee is not None:
        mine = [
            t for t in live_tickets
            if t.assignee_id == current_employee.id and status_by_id[t.status_id].category != StatusCategory.DONE
        ]
        mine.sort(key=lambda t: (t.due_date is None, t.due_date or date.max))
        for t in mine[:10]:
            s = status_by_id[t.status_id]
            my_open_tickets.append(
                MyOpenTicket(id=t.id, ticket_key=t.ticket_key, summary=t.summary, status_name=s.name, status_color=s.color, due_date=t.due_date)
            )

    # ---- Recent activity ----
    recent = list(
        db.scalars(
            select(TicketActivity)
            .join(Ticket, Ticket.id == TicketActivity.ticket_id)
            .where(Ticket.project_id == project.id)
            .order_by(TicketActivity.created_at.desc())
            .limit(15)
        )
    )
    tickets_by_id = {t.id: t for t in all_tickets}
    recent_activity = [
        RecentActivityItem(
            ticket_id=a.ticket_id, ticket_key=tickets_by_id[a.ticket_id].ticket_key if a.ticket_id in tickets_by_id else "?",
            actor_name=_employee_name(db, a.actor_id) or "Unknown", action=a.action, field_name=a.field_name,
            old_value=a.old_value, new_value=a.new_value, created_at=a.created_at,
        )
        for a in recent
    ]

    # ---- Sprint progress ----
    sprint_progress = None
    active_sprint = db.scalar(select(Sprint).where(Sprint.project_id == project.id, Sprint.status == SprintStatus.ACTIVE))
    if active_sprint is not None:
        sprint_tickets = [t for t in live_tickets if t.sprint_id == active_sprint.id]
        total_points = sum(t.story_points or 0 for t in sprint_tickets)
        completed_points = sum(
            t.story_points or 0 for t in sprint_tickets if status_by_id[t.status_id].category == StatusCategory.DONE
        )
        tickets_remaining = sum(1 for t in sprint_tickets if status_by_id[t.status_id].category != StatusCategory.DONE)
        days_remaining = (active_sprint.end_date - today).days if active_sprint.end_date else None
        sprint_progress = SprintProgress(
            sprint_id=active_sprint.id, name=active_sprint.name, completed_points=completed_points,
            total_points=total_points, days_remaining=days_remaining, tickets_remaining=tickets_remaining,
        )

    return DashboardResponse(
        kpis=kpis, status_distribution=status_distribution, workload_distribution=workload_distribution,
        creation_trend=creation_trend, resolution_time_buckets=resolution_time_buckets,
        my_open_tickets=my_open_tickets, recent_activity=recent_activity, sprint_progress=sprint_progress,
    )


CATEGORY_DISPLAY = [
    (StatusCategory.TODO, "To Do", "#6c757d"),
    (StatusCategory.INPROGRESS, "In Progress", "#0d6efd"),
    (StatusCategory.DONE, "Done", "#198754"),
]


@router.get("/dashboard", response_model=GlobalDashboardResponse)
def get_global_dashboard(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> GlobalDashboardResponse:
    """The company-wide counterpart to the per-project dashboard: the same KPIs/widgets, rolled
    up across every project. Statuses vary per project, so charts group by StatusCategory
    (To Do / In Progress / Done) instead of literal status name, matching the global board."""
    now = utcnow()
    today = now.date()
    week_ago = now - timedelta(days=7)

    projects = list(db.scalars(select(Project).where(Project.company_id == current_user.company_id)))
    project_ids = [p.id for p in projects]
    projects_by_id = {p.id: p for p in projects}

    statuses = list(db.scalars(select(TicketStatus).where(TicketStatus.project_id.in_(project_ids)))) if project_ids else []
    status_by_id = {s.id: s for s in statuses}
    status_category_by_name = {s.name: s.category for s in statuses}
    statuses_by_project: dict[int, list[TicketStatus]] = defaultdict(list)
    for s in statuses:
        statuses_by_project[s.project_id].append(s)
    default_status_name_by_project: dict[int, str] = {}
    for pid, project_statuses in statuses_by_project.items():
        default = next((s for s in project_statuses if s.is_default), project_statuses[0] if project_statuses else None)
        if default is not None:
            default_status_name_by_project[pid] = default.name

    all_tickets = list(db.scalars(select(Ticket).where(Ticket.project_id.in_(project_ids)))) if project_ids else []
    live_tickets = [t for t in all_tickets if t.deleted_at is None]

    # ---- KPIs ----
    open_count = sum(1 for t in live_tickets if status_by_id[t.status_id].category != StatusCategory.DONE)
    in_progress_count = sum(1 for t in live_tickets if status_by_id[t.status_id].category == StatusCategory.INPROGRESS)
    completed_this_week = sum(1 for t in live_tickets if t.resolved_at and t.resolved_at >= week_ago)
    completed_prior_week = sum(
        1 for t in live_tickets if t.resolved_at and week_ago - timedelta(days=7) <= t.resolved_at < week_ago
    )
    overdue_count = sum(
        1 for t in live_tickets
        if t.due_date and t.due_date < today and status_by_id[t.status_id].category != StatusCategory.DONE
    )

    activities = (
        list(
            db.scalars(
                select(TicketActivity)
                .join(Ticket, Ticket.id == TicketActivity.ticket_id)
                .where(Ticket.project_id.in_(project_ids), TicketActivity.action == "transitioned")
            )
        )
        if project_ids else []
    )
    snapshot = _category_snapshot(all_tickets, activities, status_category_by_name, default_status_name_by_project, week_ago)
    open_week_ago = sum(1 for cat in snapshot.values() if cat != StatusCategory.DONE)
    in_progress_week_ago = sum(1 for cat in snapshot.values() if cat == StatusCategory.INPROGRESS)
    overdue_week_ago = sum(
        1 for t in all_tickets
        if t.id in snapshot and snapshot[t.id] != StatusCategory.DONE and t.due_date and t.due_date < week_ago.date()
    )

    def _trend(current: int, previous: int) -> float | None:
        if previous == 0:
            return None if current == 0 else 100.0
        return round((current - previous) / previous * 100, 1)

    kpis = DashboardKpis(
        open=KpiCard(value=open_count, trend_pct=_trend(open_count, open_week_ago)),
        in_progress=KpiCard(value=in_progress_count, trend_pct=_trend(in_progress_count, in_progress_week_ago)),
        completed_this_week=KpiCard(value=completed_this_week, trend_pct=_trend(completed_this_week, completed_prior_week)),
        overdue=KpiCard(value=overdue_count, trend_pct=_trend(overdue_count, overdue_week_ago)),
    )

    # ---- Category distribution (statuses aren't comparable across projects) ----
    counts_by_category: dict[StatusCategory, int] = defaultdict(int)
    for t in live_tickets:
        counts_by_category[status_by_id[t.status_id].category] += 1
    category_distribution = [
        CategoryDistributionSlice(category=cat, label=label, color=color, count=counts_by_category.get(cat, 0))
        for cat, label, color in CATEGORY_DISPLAY
    ]

    # ---- Workload distribution ----
    members = list(db.scalars(select(ProjectMember).where(ProjectMember.project_id.in_(project_ids)))) if project_ids else []
    member_ids = {m.employee_id for m in members} | {t.assignee_id for t in live_tickets if t.assignee_id}
    workload_by_employee: dict[int, dict] = {
        eid: {"open": 0, "in_progress": 0, "overdue": 0, "points": 0} for eid in member_ids
    }
    unassigned = {"open": 0, "in_progress": 0, "overdue": 0, "points": 0}
    for t in live_tickets:
        cat = status_by_id[t.status_id].category
        if cat == StatusCategory.DONE:
            continue
        bucket = workload_by_employee[t.assignee_id] if t.assignee_id else unassigned
        bucket["open"] += 1
        if cat == StatusCategory.INPROGRESS:
            bucket["in_progress"] += 1
        if t.due_date and t.due_date < today:
            bucket["overdue"] += 1
        bucket["points"] += t.story_points or 0

    workload_distribution = [
        WorkloadEntry(
            employee_id=eid, employee_name=_employee_name(db, eid) or "Unknown",
            open_count=data["open"], in_progress_count=data["in_progress"],
            overdue_count=data["overdue"], total_points=data["points"],
        )
        for eid, data in workload_by_employee.items()
    ]
    workload_distribution.sort(key=lambda w: -w.open_count)
    if unassigned["open"]:
        workload_distribution.append(
            WorkloadEntry(
                employee_id=None, employee_name="Unassigned", open_count=unassigned["open"],
                in_progress_count=unassigned["in_progress"], overdue_count=unassigned["overdue"],
                total_points=unassigned["points"],
            )
        )

    # ---- Creation trend (last 30 days) ----
    thirty_days_ago = today - timedelta(days=29)
    counts_by_day: dict[date, int] = defaultdict(int)
    for t in all_tickets:
        d = t.created_at.date()
        if d >= thirty_days_ago:
            counts_by_day[d] += 1
    creation_trend = [
        TrendPoint(date=thirty_days_ago + timedelta(days=i), count=counts_by_day.get(thirty_days_ago + timedelta(days=i), 0))
        for i in range(30)
    ]

    # ---- Resolution time buckets ----
    bucket_counts = [0] * len(RESOLUTION_BUCKETS)
    for t in live_tickets:
        if not t.resolved_at:
            continue
        days_to_resolve = (t.resolved_at - t.created_at).total_seconds() / 86400
        for i, (_, lo, hi) in enumerate(RESOLUTION_BUCKETS):
            if days_to_resolve >= lo and (hi is None or days_to_resolve < hi):
                bucket_counts[i] += 1
                break
    resolution_time_buckets = [
        ResolutionBucket(label=RESOLUTION_BUCKETS[i][0], count=bucket_counts[i]) for i in range(len(RESOLUTION_BUCKETS))
    ]

    # ---- My open tickets ----
    my_open_tickets: list[MyOpenTicket] = []
    current_employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if current_employee is not None:
        mine = [
            t for t in live_tickets
            if t.assignee_id == current_employee.id and status_by_id[t.status_id].category != StatusCategory.DONE
        ]
        mine.sort(key=lambda t: (t.due_date is None, t.due_date or date.max))
        for t in mine[:10]:
            s = status_by_id[t.status_id]
            my_open_tickets.append(
                MyOpenTicket(id=t.id, ticket_key=t.ticket_key, summary=t.summary, status_name=s.name, status_color=s.color, due_date=t.due_date)
            )

    # ---- Recent activity ----
    recent = (
        list(
            db.scalars(
                select(TicketActivity)
                .join(Ticket, Ticket.id == TicketActivity.ticket_id)
                .where(Ticket.project_id.in_(project_ids))
                .order_by(TicketActivity.created_at.desc())
                .limit(15)
            )
        )
        if project_ids else []
    )
    tickets_by_id = {t.id: t for t in all_tickets}
    recent_activity = [
        RecentActivityItem(
            ticket_id=a.ticket_id, ticket_key=tickets_by_id[a.ticket_id].ticket_key if a.ticket_id in tickets_by_id else "?",
            actor_name=_employee_name(db, a.actor_id) or "Unknown", action=a.action, field_name=a.field_name,
            old_value=a.old_value, new_value=a.new_value, created_at=a.created_at,
        )
        for a in recent
    ]

    # ---- Active sprints (one project can only have one, but many projects can) ----
    active_sprints_rows = (
        list(db.scalars(select(Sprint).where(Sprint.project_id.in_(project_ids), Sprint.status == SprintStatus.ACTIVE)))
        if project_ids else []
    )
    active_sprints: list[SprintProgress] = []
    for sprint in active_sprints_rows:
        sprint_tickets = [t for t in live_tickets if t.sprint_id == sprint.id]
        total_points = sum(t.story_points or 0 for t in sprint_tickets)
        completed_points = sum(
            t.story_points or 0 for t in sprint_tickets if status_by_id[t.status_id].category == StatusCategory.DONE
        )
        tickets_remaining = sum(1 for t in sprint_tickets if status_by_id[t.status_id].category != StatusCategory.DONE)
        days_remaining = (sprint.end_date - today).days if sprint.end_date else None
        project = projects_by_id.get(sprint.project_id)
        active_sprints.append(
            SprintProgress(
                sprint_id=sprint.id, name=sprint.name, completed_points=completed_points, total_points=total_points,
                days_remaining=days_remaining, tickets_remaining=tickets_remaining,
                project_id=sprint.project_id, project_key=project.key if project else None,
            )
        )

    # ---- Project breakdown ----
    project_breakdown = []
    for project in sorted(projects, key=lambda p: p.name):
        project_live_tickets = [t for t in live_tickets if t.project_id == project.id]
        p_open = sum(1 for t in project_live_tickets if status_by_id[t.status_id].category != StatusCategory.DONE)
        p_overdue = sum(
            1 for t in project_live_tickets
            if t.due_date and t.due_date < today and status_by_id[t.status_id].category != StatusCategory.DONE
        )
        project_breakdown.append(
            ProjectBreakdownEntry(project_id=project.id, project_key=project.key, project_name=project.name, open_count=p_open, overdue_count=p_overdue)
        )

    return GlobalDashboardResponse(
        kpis=kpis, category_distribution=category_distribution, workload_distribution=workload_distribution,
        creation_trend=creation_trend, resolution_time_buckets=resolution_time_buckets,
        my_open_tickets=my_open_tickets, recent_activity=recent_activity,
        active_sprints=active_sprints, project_breakdown=project_breakdown,
    )


# ---- Burndown ----

@router.get("/dashboard/{project_id}/burndown", response_model=BurndownResponse)
def get_burndown(
    project_id: int, sprint_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> BurndownResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    if sprint_id is not None:
        sprint = _get_sprint_or_404(db, project.id, sprint_id)
    else:
        sprint = db.scalar(select(Sprint).where(Sprint.project_id == project.id, Sprint.status == SprintStatus.ACTIVE))
        if sprint is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active sprint")
    if not sprint.start_date or not sprint.end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sprint has no start/end dates set")

    total_points = sprint.committed_points
    total_days = (sprint.end_date - sprint.start_date).days
    tickets = list(
        db.scalars(select(Ticket).where(Ticket.sprint_id == sprint.id, Ticket.deleted_at.is_(None)))
    )
    today = utcnow().date()

    points = []
    day = sprint.start_date
    idx = 0
    while day <= sprint.end_date:
        ideal = total_points if total_days == 0 else total_points * (1 - idx / total_days)
        actual = None
        if day <= today:
            resolved_by_day = sum(
                t.story_points or 0 for t in tickets if t.resolved_at and t.resolved_at.date() <= day
            )
            actual = max(total_points - resolved_by_day, 0)
        points.append(BurndownPoint(date=day, ideal=round(ideal, 1), actual=actual))
        day += timedelta(days=1)
        idx += 1

    return BurndownResponse(sprint_id=sprint.id, sprint_name=sprint.name, total_points=total_points, points=points)


# ---- Velocity ----

@router.get("/dashboard/{project_id}/velocity", response_model=VelocityResponse)
def get_velocity(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> VelocityResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    linked_sprint_ids = select(SprintProject.sprint_id).where(SprintProject.project_id == project.id)
    sprints = list(
        db.scalars(
            select(Sprint)
            .where(
                or_(Sprint.project_id == project.id, Sprint.id.in_(linked_sprint_ids)),
                Sprint.status.in_([SprintStatus.COMPLETED, SprintStatus.CLOSED]),
            )
            .order_by(Sprint.id.desc())
            .limit(6)
        )
    )
    sprints.reverse()

    entries = []
    for sprint in sprints:
        tickets = list(db.scalars(select(Ticket).where(Ticket.sprint_id == sprint.id, Ticket.deleted_at.is_(None))))
        done_status_ids = {
            s.id
            for s in db.scalars(
                select(TicketStatus).where(
                    TicketStatus.project_id.in_(_sprint_project_ids(db, sprint)), TicketStatus.category == StatusCategory.DONE
                )
            )
        }
        completed_points = sum(t.story_points or 0 for t in tickets if t.status_id in done_status_ids)
        entries.append(VelocityEntry(sprint_id=sprint.id, sprint_name=sprint.name, committed_points=sprint.committed_points, completed_points=completed_points))

    average = round(sum(e.completed_points for e in entries) / len(entries), 1) if entries else 0.0
    return VelocityResponse(sprints=entries, average_velocity=average)


# ---- Reports ----

@router.get("/reports/sprint/{sprint_id}", response_model=SprintReportResponse)
def sprint_report(
    sprint_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> SprintReportResponse:
    sprint = db.scalar(
        select(Sprint).join(Project, Project.id == Sprint.project_id).where(
            Sprint.id == sprint_id, Project.company_id == current_user.company_id
        )
    )
    if sprint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")
    project_ids = _sprint_project_ids(db, sprint)
    projects_by_id = {p.id: p for p in db.scalars(select(Project).where(Project.id.in_(project_ids)))}
    project = projects_by_id[sprint.project_id]

    statuses = list(db.scalars(select(TicketStatus).where(TicketStatus.project_id.in_(project_ids))))
    status_by_id = {s.id: s for s in statuses}
    types = {t.id: t for t in db.scalars(select(IssueType).where(IssueType.company_id == project.company_id))}
    priorities = {p.id: p for p in db.scalars(select(TicketPriority).where(TicketPriority.company_id == project.company_id))}

    tickets = list(db.scalars(select(Ticket).where(Ticket.sprint_id == sprint.id, Ticket.deleted_at.is_(None))))
    completed = [t for t in tickets if status_by_id[t.status_id].category == StatusCategory.DONE]
    incomplete = [t for t in tickets if status_by_id[t.status_id].category != StatusCategory.DONE]
    completed_points = sum(t.story_points or 0 for t in completed)

    cycle_times = [
        (t.resolved_at - t.created_at).total_seconds() / 3600 for t in completed if t.resolved_at
    ]
    avg_cycle_time = round(sum(cycle_times) / len(cycle_times), 1) if cycle_times else None

    contribution: dict[str, int] = defaultdict(int)
    for t in completed:
        name = _employee_name(db, t.assignee_id) or "Unassigned"
        contribution[name] += 1

    return SprintReportResponse(
        sprint_id=sprint.id, sprint_name=sprint.name, goal=sprint.goal,
        start_date=sprint.start_date, end_date=sprint.end_date,
        committed_points=sprint.committed_points, completed_points=completed_points,
        completed_tickets=[
            _to_ticket_list_item(db, t, projects_by_id[t.project_id], status_by_id, types, priorities) for t in completed
        ],
        incomplete_tickets=[
            _to_ticket_list_item(db, t, projects_by_id[t.project_id], status_by_id, types, priorities) for t in incomplete
        ],
        average_cycle_time_hours=avg_cycle_time, contribution=dict(contribution),
    )


def _workload_entries(db: Session, project: Project) -> list[WorkloadEntry]:
    statuses = list(db.scalars(select(TicketStatus).where(TicketStatus.project_id == project.id)))
    status_by_id = {s.id: s for s in statuses}
    tickets = list(db.scalars(select(Ticket).where(Ticket.project_id == project.id, Ticket.deleted_at.is_(None))))
    members = list(db.scalars(select(ProjectMember).where(ProjectMember.project_id == project.id)))
    member_ids = {m.employee_id for m in members} | {t.assignee_id for t in tickets if t.assignee_id}
    today = utcnow().date()

    data: dict[int, dict] = {eid: {"open": 0, "in_progress": 0, "overdue": 0, "points": 0} for eid in member_ids}
    for t in tickets:
        if t.assignee_id is None or t.assignee_id not in data:
            continue
        cat = status_by_id[t.status_id].category
        if cat == StatusCategory.DONE:
            continue
        bucket = data[t.assignee_id]
        bucket["open"] += 1
        if cat == StatusCategory.INPROGRESS:
            bucket["in_progress"] += 1
        if t.due_date and t.due_date < today:
            bucket["overdue"] += 1
        bucket["points"] += t.story_points or 0

    entries = [
        WorkloadEntry(
            employee_id=eid, employee_name=_employee_name(db, eid) or "Unknown",
            open_count=v["open"], in_progress_count=v["in_progress"], overdue_count=v["overdue"], total_points=v["points"],
        )
        for eid, v in data.items()
    ]
    entries.sort(key=lambda e: -e.open_count)
    return entries


@router.get("/reports/workload", response_model=WorkloadReportResponse)
def workload_report(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> WorkloadReportResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    return WorkloadReportResponse(entries=_workload_entries(db, project))


@router.get("/reports/workload/export")
def workload_report_export(
    project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> StreamingResponse:
    project = _get_project_or_404(db, project_id, current_user.company_id)
    entries = _workload_entries(db, project)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Member", "Open Tickets", "In Progress", "Overdue", "Total Story Points"])
    for e in entries:
        writer.writerow([e.employee_name, e.open_count, e.in_progress_count, e.overdue_count, e.total_points])
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={project.key}_workload_report.csv"},
    )
