from datetime import date, datetime

from pydantic import BaseModel

from app.models.project import SprintStatus, StatusCategory


# ---- Projects ----

class ProjectCreate(BaseModel):
    key: str
    name: str
    description: str | None = None
    lead_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    lead_id: int | None = None
    is_active: bool | None = None


class ProjectResponse(BaseModel):
    id: int
    company_id: int
    key: str
    name: str
    description: str | None
    lead_id: int | None
    lead_name: str | None = None
    is_active: bool
    open_ticket_count: int = 0
    my_role: str = "viewer"
    is_watching: bool = False

    model_config = {"from_attributes": True}


class ProjectMemberCreate(BaseModel):
    employee_id: int
    role: str = "developer"


class ProjectMemberRoleUpdate(BaseModel):
    role: str


class ProjectMemberResponse(BaseModel):
    id: int
    project_id: int
    employee_id: int
    employee_name: str
    employee_code: str
    role: str

    model_config = {"from_attributes": True}


# ---- Labels ----

class LabelCreate(BaseModel):
    name: str
    color: str = "#6c757d"


class TicketLabelAssign(BaseModel):
    label_id: int


class LabelResponse(BaseModel):
    id: int
    project_id: int
    name: str
    color: str

    model_config = {"from_attributes": True}


# ---- Time tracking ----

class WorkLogCreate(BaseModel):
    minutes_spent: int
    log_date: date
    description: str | None = None


class WorkLogResponse(BaseModel):
    id: int
    ticket_id: int
    author_id: int
    author_name: str
    minutes_spent: int
    log_date: date
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TimeReportEntry(BaseModel):
    employee_id: int
    employee_name: str
    total_minutes: int
    ticket_breakdown: dict[str, int]


class TimeReportResponse(BaseModel):
    entries: list[TimeReportEntry]


# ---- Statuses ----

class TicketStatusCreate(BaseModel):
    name: str
    category: StatusCategory
    color: str = "#6c757d"
    position: int | None = None
    wip_limit: int | None = None


class TicketStatusUpdate(BaseModel):
    name: str | None = None
    category: StatusCategory | None = None
    color: str | None = None
    position: int | None = None
    wip_limit: int | None = None


class TicketStatusResponse(BaseModel):
    id: int
    project_id: int
    name: str
    category: StatusCategory
    color: str
    position: int
    is_default: bool
    wip_limit: int | None

    model_config = {"from_attributes": True}


# ---- Sprints ----

class SprintCreate(BaseModel):
    name: str
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    linked_project_ids: list[int] | None = None


class SprintUpdate(BaseModel):
    name: str | None = None
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    linked_project_ids: list[int] | None = None


class SprintResponse(BaseModel):
    id: int
    project_id: int
    name: str
    goal: str | None
    status: SprintStatus
    start_date: date | None
    end_date: date | None
    ticket_count: int = 0
    completed_points: int = 0
    total_points: int = 0
    committed_points: int = 0
    linked_project_ids: list[int] = []

    model_config = {"from_attributes": True}


class SprintCompleteRequest(BaseModel):
    incomplete_action: str = "backlog"  # "backlog" | "next_sprint" | "keep"
    target_sprint_id: int | None = None


class TicketSprintAssign(BaseModel):
    sprint_id: int | None = None


class TicketPositionUpdate(BaseModel):
    status_id: int
    position: int


class TicketBulkUpdateRequest(BaseModel):
    ticket_ids: list[int]
    status_id: int | None = None
    assignee_id: int | None = None
    sprint_id: int | None = None
    delete: bool = False


class TicketBulkUpdateResponse(BaseModel):
    updated_count: int


# ---- Catalogs ----

class IssueTypeCreate(BaseModel):
    name: str
    icon: str = "bi-bookmark"
    color: str = "#6c757d"
    position: int | None = None


class IssueTypeResponse(BaseModel):
    id: int
    company_id: int
    name: str
    icon: str
    color: str
    position: int

    model_config = {"from_attributes": True}


class TicketPriorityCreate(BaseModel):
    name: str
    icon: str = "bi-dash"
    color: str = "#6c757d"
    position: int | None = None


class TicketPriorityResponse(BaseModel):
    id: int
    company_id: int
    name: str
    icon: str
    color: str
    position: int

    model_config = {"from_attributes": True}


# ---- Tickets ----

class TicketCreate(BaseModel):
    project_id: int
    summary: str
    description: str | None = None
    issue_type_id: int
    priority_id: int | None = None
    assignee_id: int | None = None
    parent_id: int | None = None
    epic_id: int | None = None
    sprint_id: int | None = None
    story_points: int | None = None
    original_estimate: int | None = None
    due_date: date | None = None


class TicketUpdate(BaseModel):
    summary: str | None = None
    description: str | None = None
    issue_type_id: int | None = None
    priority_id: int | None = None
    assignee_id: int | None = None
    parent_id: int | None = None
    epic_id: int | None = None
    story_points: int | None = None
    original_estimate: int | None = None
    remaining_estimate: int | None = None
    due_date: date | None = None


class TicketTransitionRequest(BaseModel):
    status_id: int


class TicketListItem(BaseModel):
    id: int
    project_id: int
    project_key: str
    ticket_key: str
    summary: str
    issue_type: IssueTypeResponse
    status: TicketStatusResponse
    priority: TicketPriorityResponse | None
    assignee_id: int | None
    assignee_name: str | None
    reporter_id: int
    reporter_name: str
    sprint_id: int | None
    board_position: int
    story_points: int | None
    due_date: date | None
    updated_at: datetime
    labels: list[LabelResponse] = []

    model_config = {"from_attributes": True}


class TicketDetailResponse(BaseModel):
    id: int
    project_id: int
    project_key: str
    ticket_key: str
    summary: str
    description: str | None
    issue_type: IssueTypeResponse
    status: TicketStatusResponse
    priority: TicketPriorityResponse | None
    reporter_id: int
    reporter_name: str
    assignee_id: int | None
    assignee_name: str | None
    parent_id: int | None
    epic_id: int | None
    sprint_id: int | None
    board_position: int
    story_points: int | None
    original_estimate: int | None
    remaining_estimate: int | None
    time_spent: int
    due_date: date | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    is_watching: bool = False
    watcher_count: int = 0
    labels: list[LabelResponse] = []
    my_role: str = "viewer"

    model_config = {"from_attributes": True}


# ---- Comments ----

class TicketCommentCreate(BaseModel):
    body: str
    is_internal: bool = False


class TicketCommentUpdate(BaseModel):
    body: str


class TicketCommentResponse(BaseModel):
    id: int
    ticket_id: int
    author_id: int
    author_name: str
    body: str
    is_internal: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---- Attachments ----

class TicketAttachmentResponse(BaseModel):
    id: int
    ticket_id: int
    uploader_id: int
    uploader_name: str
    file_name: str
    file_size: int
    mime_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- Board & Backlog ----

class BoardResponse(BaseModel):
    statuses: list[TicketStatusResponse]
    tickets: list[TicketListItem]
    sprint: SprintResponse | None = None


class BacklogResponse(BaseModel):
    active_sprint: SprintResponse | None
    active_sprint_tickets: list[TicketListItem]
    future_sprints: list[SprintResponse]
    future_sprint_tickets: dict[int, list[TicketListItem]]
    backlog_tickets: list[TicketListItem]


class BoardProjectSummary(BaseModel):
    id: int
    key: str
    name: str


class GlobalBoardResponse(BaseModel):
    projects: list[BoardProjectSummary]
    tickets: list[TicketListItem]


class TicketCategoryUpdate(BaseModel):
    category: StatusCategory


# ---- Dashboard ----

class KpiCard(BaseModel):
    value: int
    trend_pct: float | None = None


class DashboardKpis(BaseModel):
    open: KpiCard
    in_progress: KpiCard
    completed_this_week: KpiCard
    overdue: KpiCard


class StatusDistributionSlice(BaseModel):
    status_id: int
    name: str
    color: str
    count: int


class WorkloadEntry(BaseModel):
    employee_id: int | None
    employee_name: str
    open_count: int
    in_progress_count: int
    overdue_count: int
    total_points: int


class TrendPoint(BaseModel):
    date: date
    count: int


class ResolutionBucket(BaseModel):
    label: str
    count: int


class MyOpenTicket(BaseModel):
    id: int
    ticket_key: str
    summary: str
    status_name: str
    status_color: str
    due_date: date | None


class RecentActivityItem(BaseModel):
    ticket_id: int
    ticket_key: str
    actor_name: str
    action: str
    field_name: str | None
    old_value: str | None
    new_value: str | None
    created_at: datetime


class SprintProgress(BaseModel):
    sprint_id: int
    name: str
    completed_points: int
    total_points: int
    days_remaining: int | None
    tickets_remaining: int
    project_id: int | None = None
    project_key: str | None = None


class DashboardResponse(BaseModel):
    kpis: DashboardKpis
    status_distribution: list[StatusDistributionSlice]
    workload_distribution: list[WorkloadEntry]
    creation_trend: list[TrendPoint]
    resolution_time_buckets: list[ResolutionBucket]
    my_open_tickets: list[MyOpenTicket]
    recent_activity: list[RecentActivityItem]
    sprint_progress: SprintProgress | None


class CategoryDistributionSlice(BaseModel):
    category: StatusCategory
    label: str
    color: str
    count: int


class ProjectBreakdownEntry(BaseModel):
    project_id: int
    project_key: str
    project_name: str
    open_count: int
    overdue_count: int


class GlobalDashboardResponse(BaseModel):
    kpis: DashboardKpis
    category_distribution: list[CategoryDistributionSlice]
    workload_distribution: list[WorkloadEntry]
    creation_trend: list[TrendPoint]
    resolution_time_buckets: list[ResolutionBucket]
    my_open_tickets: list[MyOpenTicket]
    recent_activity: list[RecentActivityItem]
    active_sprints: list[SprintProgress]
    project_breakdown: list[ProjectBreakdownEntry]


class BurndownPoint(BaseModel):
    date: date
    ideal: float
    actual: float | None


class BurndownResponse(BaseModel):
    sprint_id: int
    sprint_name: str
    total_points: int
    points: list[BurndownPoint]


class VelocityEntry(BaseModel):
    sprint_id: int
    sprint_name: str
    committed_points: int
    completed_points: int


class VelocityResponse(BaseModel):
    sprints: list[VelocityEntry]
    average_velocity: float


class SprintReportResponse(BaseModel):
    sprint_id: int
    sprint_name: str
    goal: str | None
    start_date: date | None
    end_date: date | None
    committed_points: int
    completed_points: int
    completed_tickets: list[TicketListItem]
    incomplete_tickets: list[TicketListItem]
    average_cycle_time_hours: float | None
    contribution: dict[str, int]


class WorkloadReportResponse(BaseModel):
    entries: list[WorkloadEntry]


# ---- Activity ----

class TicketActivityResponse(BaseModel):
    id: int
    ticket_id: int
    actor_id: int
    actor_name: str
    action: str
    field_name: str | None
    old_value: str | None
    new_value: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
