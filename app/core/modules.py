from app.api.deps import HR_WRITE_ROLES

ALWAYS_ON_MODULE = "profile"

MODULE_CATALOG: dict[str, str] = {
    "profile": "My Profile",
    "documents": "Upload Documents",
    "leave": "My Leave",
    "attendance": "My Attendance",
    "kra": "My KRA",
    "pms": "My Performance",
    "hr_employees": "Employees",
    "hr_onboarding": "Onboarding",
    "hr_documents": "Document Review",
    "hr_leave": "Leave Management",
    "hr_attendance": "Attendance Management",
    "hr_kra": "KRA Management",
    "hr_pms": "Performance Management",
    "manager_team": "Team Approvals",
}

BASE_MODULES = ("profile", "documents", "leave", "attendance", "kra", "pms")
HR_MODULES = (
    "hr_employees",
    "hr_onboarding",
    "hr_documents",
    "hr_leave",
    "hr_attendance",
    "hr_kra",
    "hr_pms",
)
MANAGER_MODULES = ("manager_team",)


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
    replaces the role-based default entirely - "My Profile" is always force-included since
    every account needs at least a way to manage its own profile.
    """
    if module_access_json is not None:
        modules = {m for m in module_access_json if m in MODULE_CATALOG}
        modules.add(ALWAYS_ON_MODULE)
        return sorted(modules)
    return default_modules_for(role, is_manager)
