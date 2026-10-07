"""
Modelos Pydantic para Fase 2: API endpoints de permisos.
Request/Response schemas para FastAPI.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ============================================================================
# USUARIOS
# ============================================================================

class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=80)
    role: str = Field(..., description="admin, supervisor, analyst, dba")
    department: Optional[str] = None
    team_id: Optional[str] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=12, max_length=1024)


class UserUpdate(BaseModel):
    role: Optional[str] = None
    department: Optional[str] = None
    team_id: Optional[str] = None
    status: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    department: Optional[str]
    team_id: Optional[str]
    status: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# PERMISOS
# ============================================================================

class PermissionResponse(BaseModel):
    id: str
    name: str
    display_name: str
    description: Optional[str]
    resource_type: str
    action: str

    class Config:
        from_attributes = True


class GrantPermissionRequest(BaseModel):
    user_id: str
    permission_id: str
    expires_at: Optional[float] = None


class RevokePermissionRequest(BaseModel):
    user_id: str
    permission_id: str


class UserPermissionsResponse(BaseModel):
    user_id: str
    permissions: List[str]  # Lista de nombres de permisos


# ============================================================================
# EQUIPOS
# ============================================================================

class TeamBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    manager_id: Optional[str] = None


class TeamCreate(TeamBase):
    pass


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    manager_id: Optional[str] = None


class TeamResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    manager_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TeamMemberResponse(BaseModel):
    id: str
    team_id: str
    user_id: str
    role_in_team: str
    created_at: datetime

    class Config:
        from_attributes = True


class AddTeamMemberRequest(BaseModel):
    user_id: str
    role_in_team: str = "member"


# ============================================================================
# ACCESO A RECURSOS
# ============================================================================

class GrantResourceAccessRequest(BaseModel):
    user_id: str
    resource_type: str
    resource_id: str
    access_level: str = Field(..., description="read, write, o admin")
    expires_at: Optional[float] = None


class ResourceAccessResponse(BaseModel):
    id: str
    user_id: str
    resource_type: str
    resource_id: str
    access_level: str
    assigned_by: Optional[str]
    assigned_at: datetime
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================================
# AUDITORÍA
# ============================================================================

class AuditLogResponse(BaseModel):
    id: str
    user_id: Optional[str]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    old_value: Optional[dict]
    new_value: Optional[dict]
    ip_address: Optional[str]
    status: str
    error_message: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True


class AuditLogFilters(BaseModel):
    user_id: Optional[str] = None
    action: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


# ============================================================================
# DASHBOARD
# ============================================================================

class DashboardStats(BaseModel):
    total_jobs: int
    total_users: int
    total_teams: int
    active_users: int


class JobSummary(BaseModel):
    id: str
    status: str
    created_by: Optional[str]
    created_at: datetime


class DashboardResponse(BaseModel):
    role: str
    stats: DashboardStats
    recent_jobs: List[JobSummary]
    teams: Optional[List[TeamResponse]]
    users: Optional[List[UserResponse]]
    audit_entries: Optional[List[AuditLogResponse]]


# ============================================================================
# RESPUESTAS GENERALES
# ============================================================================

class ErrorResponse(BaseModel):
    detail: str
    status_code: int


class SuccessResponse(BaseModel):
    message: str
    data: Optional[dict] = None
