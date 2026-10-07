"""
Fase 2: Endpoints de API para gestión de permisos, usuarios, equipos y dashboard.
Estos endpoints se agregan a main.py mediante include_router().
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from uuid import uuid4
from typing import List

from apps.api.database import (
    SessionLocal, UserORM, ProcessingJobORM,
    get_db,
)
from apps.api.models_permissions import (
    TeamORM, TeamMemberORM, PermissionORM, AuditLogORM,
    ResourceAccessORM,
)
from apps.api.permissions import (
    has_permission, can_access_resource, 
    get_user_permissions, grant_permission_to_user,
    revoke_permission_from_user, grant_resource_access,
    revoke_resource_access, log_audit_event,
    create_default_permissions, create_default_roles,
)
from apps.api.main import get_current_user, require_admin
from apps.api.schemas_phase2 import (
    UserCreate, UserUpdate, UserResponse, PermissionResponse,
    GrantPermissionRequest, RevokePermissionRequest, UserPermissionsResponse,
    TeamCreate, TeamUpdate, TeamResponse, TeamMemberResponse, AddTeamMemberRequest,
    GrantResourceAccessRequest, ResourceAccessResponse,
    AuditLogResponse, AuditLogFilters, DashboardResponse, DashboardStats,
    JobSummary, SuccessResponse,
)
from packages.domain.permissions_enums import RoleType, AuditAction

router = APIRouter(prefix="/api/v1", tags=["Fase 2: Permissions API"])


# ============================================================================
# USUARIOS
# ============================================================================

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Lista usuarios.
    - Admin: ve todos los usuarios
    - Supervisor: ve su equipo
    - Analyst/DBA: no tienen acceso
    """
    if current_user.role == RoleType.ADMIN.value:
        users = session.query(UserORM).all()
    elif current_user.role == RoleType.SUPERVISOR.value:
        # Supervisor ve su equipo
        users = session.query(UserORM).filter(
            UserORM.team_id == current_user.team_id
        ).all()
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver usuarios"
        )
    
    log_audit_event(
        session, AuditAction.AUDIT_LOG_VIEWED.value,
        user_id=current_user.id,
        resource_type="user",
        ip_address=None,  # Se puede pasar desde request.client.host
    )
    
    return users


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Obtener detalles de un usuario."""
    user = session.get(UserORM, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Verificar acceso
    if current_user.id != user_id and current_user.role != RoleType.ADMIN.value:
        raise HTTPException(status_code=403, detail="No tienes permiso")
    
    return user


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Crear nuevo usuario (solo admin)."""
    
    # Verificar que no exista
    existing = session.query(UserORM).filter(
        UserORM.username == payload.username.lower()
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    
    # Importar hash_password
    from apps.api.auth import hash_password
    
    user = UserORM(
        id=str(uuid4()),
        username=payload.username.lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        department=payload.department,
        status="active",
    )
    session.add(user)
    session.commit()
    
    # Auditoría
    log_audit_event(
        session, AuditAction.USER_CREATED.value,
        user_id=current_user.id,
        resource_type="user",
        resource_id=user.id,
        new_value={"username": user.username, "role": user.role}
    )
    
    session.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Actualizar usuario (admin o el mismo usuario)."""
    user = session.get(UserORM, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Verificar acceso
    if current_user.id != user_id and current_user.role != RoleType.ADMIN.value:
        raise HTTPException(status_code=403, detail="No tienes permiso")
    
    old_value = {
        "role": user.role,
        "department": user.department,
        "status": user.status,
    }
    
    if payload.role:
        user.role = payload.role
    if payload.department:
        user.department = payload.department
    if payload.status:
        user.status = payload.status
    if payload.team_id:
        user.team_id = payload.team_id
    
    session.commit()
    
    # Auditoría
    log_audit_event(
        session, AuditAction.USER_UPDATED.value,
        user_id=current_user.id,
        resource_type="user",
        resource_id=user_id,
        old_value=old_value,
        new_value={"role": user.role, "department": user.department, "status": user.status}
    )
    
    session.refresh(user)
    return user


# ============================================================================
# PERMISOS
# ============================================================================

@router.get("/permissions", response_model=List[PermissionResponse])
async def list_permissions(
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Listar todos los permisos disponibles."""
    permissions = session.query(PermissionORM).all()
    return permissions


@router.get("/users/{user_id}/permissions", response_model=UserPermissionsResponse)
async def get_user_permissions_endpoint(
    user_id: str,
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Obtener permisos de un usuario."""
    if current_user.id != user_id and current_user.role != RoleType.ADMIN.value:
        raise HTTPException(status_code=403, detail="No tienes permiso")
    
    permissions = get_user_permissions(session, user_id)
    
    return UserPermissionsResponse(
        user_id=user_id,
        permissions=list(permissions)
    )


@router.post("/users/{user_id}/permissions")
async def grant_permission_endpoint(
    user_id: str,
    payload: GrantPermissionRequest,
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Otorgar permiso a usuario."""
    user = session.get(UserORM, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    permission = session.get(PermissionORM, payload.permission_id)
    if not permission:
        raise HTTPException(status_code=404, detail="Permiso no encontrado")
    
    grant_permission_to_user(
        session, user_id, payload.permission_id,
        current_user.id, payload.expires_at
    )
    
    # Auditoría
    log_audit_event(
        session, AuditAction.USER_PERMISSION_GRANTED.value,
        user_id=current_user.id,
        resource_type="user",
        resource_id=user_id,
        new_value={"permission": permission.name}
    )
    
    return SuccessResponse(
        message="Permiso otorgado exitosamente",
        data={"user_id": user_id, "permission_id": payload.permission_id}
    )


@router.delete("/users/{user_id}/permissions/{permission_id}")
async def revoke_permission_endpoint(
    user_id: str,
    permission_id: str,
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Revocar permiso de usuario."""
    success = revoke_permission_from_user(session, user_id, permission_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Permiso no encontrado para este usuario")
    
    # Auditoría
    log_audit_event(
        session, AuditAction.USER_PERMISSION_REVOKED.value,
        user_id=current_user.id,
        resource_type="user",
        resource_id=user_id,
    )
    
    return SuccessResponse(message="Permiso revocado exitosamente")


# ============================================================================
# EQUIPOS
# ============================================================================

@router.get("/teams", response_model=List[TeamResponse])
async def list_teams(
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Listar equipos."""
    if current_user.role == RoleType.ADMIN.value:
        teams = session.query(TeamORM).all()
    else:
        # No-admin solo ve su equipo
        if current_user.team_id:
            teams = session.query(TeamORM).filter(
                TeamORM.id == current_user.team_id
            ).all()
        else:
            teams = []
    
    return teams


@router.post("/teams", response_model=TeamResponse, status_code=201)
async def create_team(
    payload: TeamCreate,
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Crear nuevo equipo (solo admin)."""
    
    team = TeamORM(
        id=str(uuid4()),
        name=payload.name,
        description=payload.description,
        manager_id=payload.manager_id or current_user.id,
    )
    session.add(team)
    session.commit()
    
    # Auditoría
    log_audit_event(
        session, AuditAction.TEAM_CREATED.value,
        user_id=current_user.id,
        resource_type="team",
        resource_id=team.id,
        new_value={"name": team.name}
    )
    
    session.refresh(team)
    return team


@router.post("/teams/{team_id}/members", response_model=TeamMemberResponse, status_code=201)
async def add_team_member(
    team_id: str,
    payload: AddTeamMemberRequest,
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Agregar usuario a equipo."""
    
    team = session.get(TeamORM, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    
    # Verificar que el usuario exista
    user = session.get(UserORM, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Verificar que no sea miembro ya
    existing = session.query(TeamMemberORM).filter(
        TeamMemberORM.team_id == team_id,
        TeamMemberORM.user_id == payload.user_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Usuario ya es miembro del equipo")
    
    member = TeamMemberORM(
        id=str(uuid4()),
        team_id=team_id,
        user_id=payload.user_id,
        role_in_team=payload.role_in_team,
    )
    session.add(member)
    
    # Actualizar team_id del usuario
    user.team_id = team_id
    
    session.commit()
    
    # Auditoría
    log_audit_event(
        session, AuditAction.USER_ADDED_TO_TEAM.value,
        user_id=current_user.id,
        resource_type="team",
        resource_id=team_id,
        new_value={"user_id": payload.user_id}
    )
    
    session.refresh(member)
    return member


# ============================================================================
# ACCESO A RECURSOS
# ============================================================================

@router.post("/resource-access")
async def grant_resource_access_endpoint(
    payload: GrantResourceAccessRequest,
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Otorgar acceso a un recurso específico."""
    
    grant_resource_access(
        session,
        payload.user_id,
        payload.resource_type,
        payload.resource_id,
        payload.access_level,
        current_user.id,
        payload.expires_at,
    )
    
    # Auditoría
    log_audit_event(
        session, AuditAction.RESOURCE_ACCESS_GRANTED.value,
        user_id=current_user.id,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        new_value={"user_id": payload.user_id, "access_level": payload.access_level}
    )
    
    return SuccessResponse(message="Acceso otorgado exitosamente")


@router.delete("/resource-access/{user_id}/{resource_type}/{resource_id}")
async def revoke_resource_access_endpoint(
    user_id: str,
    resource_type: str,
    resource_id: str,
    current_user: UserORM = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Revocar acceso a un recurso."""
    
    success = revoke_resource_access(session, user_id, resource_type, resource_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Acceso no encontrado")
    
    # Auditoría
    log_audit_event(
        session, AuditAction.RESOURCE_ACCESS_REVOKED.value,
        user_id=current_user.id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    
    return SuccessResponse(message="Acceso revocado exitosamente")


# ============================================================================
# AUDITORÍA
# ============================================================================

@router.get("/audit-log", response_model=List[AuditLogResponse])
async def get_audit_log(
    limit: int = 100,
    offset: int = 0,
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Obtener logs de auditoría.
    - Admin: ve todo
    - Supervisor: ve su equipo
    - Otros: denegar
    """
    
    if current_user.role != RoleType.ADMIN.value and \
       current_user.role != RoleType.SUPERVISOR.value and \
       current_user.role != RoleType.DBA.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver auditoría"
        )
    
    query = session.query(AuditLogORM).order_by(AuditLogORM.timestamp.desc())
    
    # Supervisor solo ve de su equipo
    if current_user.role == RoleType.SUPERVISOR.value:
        team_user_ids = session.query(TeamMemberORM.user_id).filter(
            TeamMemberORM.team_id == current_user.team_id
        ).all()
        team_user_ids = [u[0] for u in team_user_ids]
        query = query.filter(AuditLogORM.user_id.in_(team_user_ids))
    
    logs = query.limit(limit).offset(offset).all()
    return logs


# ============================================================================
# DASHBOARD
# ============================================================================

@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    current_user: UserORM = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """
    Dashboard personalizado según el rol del usuario.
    - Admin: ve TODO
    - Supervisor: su equipo + propios
    - Analyst: solo sus trabajos
    - DBA: estadísticas del sistema
    """
    
    # Contar trabajos
    total_jobs_query = session.query(func.count(ProcessingJobORM.id))
    
    if current_user.role == RoleType.ADMIN.value:
        total_jobs = total_jobs_query.scalar() or 0
        total_users = session.query(func.count(UserORM.id)).scalar() or 0
        total_teams = session.query(func.count(TeamORM.id)).scalar() or 0
        active_users = session.query(func.count(UserORM.id)).filter(
            UserORM.status == "active"
        ).scalar() or 0
        
        recent_jobs = session.query(ProcessingJobORM).order_by(
            ProcessingJobORM.queued_at.desc()
        ).limit(10).all()
        
        teams = session.query(TeamORM).all()
        users = session.query(UserORM).all()
        
    elif current_user.role == RoleType.SUPERVISOR.value:
        # Solo del equipo
        team_user_ids = [current_user.id]
        if current_user.team_id:
            team_users = session.query(TeamMemberORM.user_id).filter(
                TeamMemberORM.team_id == current_user.team_id
            ).all()
            team_user_ids.extend([u[0] for u in team_users])
        
        total_jobs = total_jobs_query.filter(
            ProcessingJobORM.created_by.in_(team_user_ids)
        ).scalar() or 0
        
        total_users = len(team_user_ids)
        total_teams = 1 if current_user.team_id else 0
        active_users = session.query(func.count(UserORM.id)).filter(
            UserORM.status == "active",
            UserORM.id.in_(team_user_ids)
        ).scalar() or 0
        
        recent_jobs = session.query(ProcessingJobORM).filter(
            ProcessingJobORM.created_by.in_(team_user_ids)
        ).order_by(ProcessingJobORM.queued_at.desc()).limit(10).all()
        
        teams = None
        users = session.query(UserORM).filter(
            UserORM.id.in_(team_user_ids)
        ).all()
    
    else:  # analyst o dba
        # Solo sus trabajos
        total_jobs = total_jobs_query.filter(
            ProcessingJobORM.created_by == current_user.id
        ).scalar() or 0
        
        total_users = 1
        total_teams = 0
        active_users = 1 if current_user.status == "active" else 0
        
        recent_jobs = session.query(ProcessingJobORM).filter(
            ProcessingJobORM.created_by == current_user.id
        ).order_by(ProcessingJobORM.queued_at.desc()).limit(10).all()
        
        teams = None
        users = None
    
    # Auditoría
    log_audit_event(
        session, AuditAction.AUDIT_LOG_VIEWED.value,
        user_id=current_user.id,
    )
    
    # Convertir jobs a schema
    jobs_data = [
        JobSummary(
            id=job.id,
            status=job.status,
            created_by=job.created_by,
            created_at=job.queued_at
        )
        for job in recent_jobs
    ]
    
    return DashboardResponse(
        role=current_user.role,
        stats=DashboardStats(
            total_jobs=total_jobs,
            total_users=total_users,
            total_teams=total_teams,
            active_users=active_users,
        ),
        recent_jobs=jobs_data,
        teams=teams,
        users=users,
    )
