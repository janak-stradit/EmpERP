from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.project import Project, ProjectMember
from app.models.user import User

PROJECT_ROLES = ("admin", "manager", "developer", "tester", "viewer")

# Mirrors the Phase 5 permission matrix: which project roles may perform each action.
PERMISSIONS: dict[str, set[str]] = {
    "create_ticket": {"admin", "manager", "developer", "tester"},
    "edit_any_ticket": {"admin", "manager"},
    "edit_own_ticket": {"admin", "manager", "developer", "tester"},
    "delete_ticket": {"admin", "manager"},
    "transition_ticket": {"admin", "manager", "developer", "tester"},
    "comment": {"admin", "manager", "developer", "tester"},
    "log_work": {"admin", "manager", "developer", "tester"},
    "manage_sprints": {"admin", "manager"},
    "manage_project": {"admin"},
    "export_reports": {"admin", "manager"},
}


def get_project_role(db: Session, project: Project, current_user: User) -> str:
    """Company-level super_admin/admin always act as project admins. Otherwise, an explicit
    ProjectMember role applies; any other company member defaults to read-only "viewer"."""
    if current_user.role.value in ("super_admin", "admin"):
        return "admin"
    employee = db.scalar(select(Employee).where(Employee.user_id == current_user.id, Employee.deleted_at.is_(None)))
    if employee is None:
        return "viewer"
    member = db.scalar(
        select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.employee_id == employee.id)
    )
    if member is None or member.role not in PROJECT_ROLES:
        return "viewer"
    return member.role


def require_permission(db: Session, project: Project, current_user: User, action: str) -> str:
    role = get_project_role(db, project, current_user)
    if role not in PERMISSIONS[action]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient project permissions")
    return role
