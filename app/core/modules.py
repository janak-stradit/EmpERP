from app.api.deps import HR_WRITE_ROLES

ALWAYS_ON_MODULES = {"profile", "activity_tracker"}

MODULE_CATALOG: dict[str, str] = {
    "profile": "My Profile",
    "activity_tracker": "Activity Tracker",
    "pms": "My Performance",
    "hr_employees": "Employees",
    "admin_team_mapping": "Team Mapping",
    "manager_team": "Team Approvals",
    "manager_activities": "Team Activities",
}

BASE_MODULES = ("profile", "activity_tracker", "pms")
HR_MODULES = (
    "hr_employees",
    "admin_team_mapping",
)
MANAGER_MODULES = ("manager_team", "manager_activities")


def default_modules_for(role: str, is_manager: bool) -> list[str]:
    """The standard role-based module set, unchanged from the app's original behavior."""
    modules = list(BASE_MODULES)
    if role in HR_WRITE_ROLES:
        modules.extend(HR_MODULES)
    if is_manager:
        modules.extend(MANAGER_MODULES)
    return modules


def effective_modules_for(module_access_json: list[str] | None, role: str, is_manager: bool) -> list[str]:
    """Resolves an employee's actual dashboard modules.

    A Super Admin-configured override (module_access_json not None) is authoritative and
    replaces the role-based default entirely - "My Profile" and "Activity Tracker" are always
    force-included.
    """
    if module_access_json is not None:
        modules = {m for m in module_access_json if m in MODULE_CATALOG}
        modules.update(ALWAYS_ON_MODULES)
        return sorted(modules)
    return default_modules_for(role, is_manager)
