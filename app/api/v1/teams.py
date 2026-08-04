from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_db, require_role, ADMIN_ROLES
from app.core.audit import log_audit
from app.api.deps import get_client_ip
from app.models.employee import Employee
from app.models.team import TeamMapping
from app.models.user import User
from app.schemas.team import TeamMappingCreate, TeamMappingResponse

router = APIRouter(prefix="/teams", tags=["teams"])

@router.get("/mappings", response_model=list[TeamMappingResponse])
def get_mappings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*ADMIN_ROLES))
):
    employee_alias = aliased(Employee)
    manager_alias = aliased(Employee)
    employee_user_alias = aliased(User)
    manager_user_alias = aliased(User)
    
    results = db.execute(
        select(TeamMapping, employee_user_alias.full_name, manager_user_alias.full_name)
        .join(employee_alias, TeamMapping.employee_id == employee_alias.id)
        .join(employee_user_alias, employee_alias.user_id == employee_user_alias.id)
        .join(manager_alias, TeamMapping.manager_id == manager_alias.id)
        .join(manager_user_alias, manager_alias.user_id == manager_user_alias.id)
        .where(TeamMapping.company_id == current_user.company_id)
    ).all()
    
    response = []
    for mapping, emp_name, mgr_name in results:
        response.append(
            TeamMappingResponse(
                id=mapping.id,
                employee_id=mapping.employee_id,
                employee_name=emp_name,
                manager_id=mapping.manager_id,
                manager_name=mgr_name
            )
        )
    return response

@router.post("/map", response_model=TeamMappingResponse, status_code=status.HTTP_201_CREATED)
def map_team(
    payload: TeamMappingCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*ADMIN_ROLES))
):
    employee = db.scalar(select(Employee).where(Employee.id == payload.employee_id, Employee.company_id == current_user.company_id))
    manager = db.scalar(select(Employee).where(Employee.id == payload.manager_id, Employee.company_id == current_user.company_id))
    
    if not employee or not manager:
        raise HTTPException(status_code=400, detail="Invalid employee or manager ID")
        
    if payload.employee_id == payload.manager_id:
        raise HTTPException(status_code=400, detail="Employee cannot be their own manager")

    existing = db.scalar(select(TeamMapping).where(TeamMapping.employee_id == payload.employee_id))
    
    if existing:
        if existing.manager_id == payload.manager_id:
            raise HTTPException(status_code=400, detail="Mapping already exists")
        existing.manager_id = payload.manager_id
        db.commit()
        db.refresh(existing)
        mapping = existing
    else:
        mapping = TeamMapping(
            company_id=current_user.company_id,
            employee_id=payload.employee_id,
            manager_id=payload.manager_id
        )
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
        
    log_audit(
        db,
        user_id=current_user.id,
        action="team_mapping_updated",
        entity_type="team_mapping",
        entity_id=mapping.id,
        ip_address=get_client_ip(request),
    )
    
    emp_user = db.scalar(select(User).where(User.id == employee.user_id))
    mgr_user = db.scalar(select(User).where(User.id == manager.user_id))
    
    return TeamMappingResponse(
        id=mapping.id,
        employee_id=mapping.employee_id,
        employee_name=emp_user.full_name,
        manager_id=mapping.manager_id,
        manager_name=mgr_user.full_name
    )
