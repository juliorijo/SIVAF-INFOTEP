"""
Lógica centralizada de permisos y autorización.
Proporciona funciones para verificar permisos de usuarios.
"""

from __future__ import annotations

import time
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy import and_, select

from apps.api.models_permissions import (
    PermissionORM,
    ResourceAccessORM,
    RolePermissionORM,
    UserPermissionORM,
    AuditLogORM,
    RoleORM,
    TeamORM,
    TeamMemberORM,
)
from apps.api.database import UserORM
from packages.domain.permissions_enums import AccessLevel, PermissionAction, ResourceType, RoleType, AuditAction


def get_user_role_permissions(session: Session, user_id: str) -> set[str]:
    """
    Obtiene todos los permisos de un usuario basado en su rol.
    
    Returns:
        Set de nombres de permisos (ej: {'create_job', 'read_job', 'review_job'})
    """
    user = session.get(UserORM, user_id)
    if not user:
        return set()
    
    # Obtener permisos basados en el rol del usuario
    role_perms = session.query(PermissionORM.name).join(
        RolePermissionORM,
        RolePermissionORM.permission_id == PermissionORM.id
    ).filter(
        RolePermissionORM.role_name == user.role
    ).all()
    
    return {perm.name for perm in role_perms}


def get_user_extra_permissions(session: Session, user_id: str) -> set[str]:
    """
    Obtiene permisos extras asignados específicamente al usuario (no por su rol).
    
    Returns:
        Set de nombres de permisos adicionales
    """
    extra_perms = session.query(PermissionORM.name).join(
        UserPermissionORM,
        UserPermissionORM.permission_id == PermissionORM.id
    ).filter(
        UserPermissionORM.user_id == user_id,
        # Filtrar permisos expirados
        (UserPermissionORM.expires_at.is_(None) | (UserPermissionORM.expires_at > time.time()))
    ).all()
    
    return {perm.name for perm in extra_perms}


def get_user_permissions(session: Session, user_id: str) -> set[str]:
    """
    Obtiene TODOS los permisos de un usuario (role + extras).
    
    Returns:
        Set de nombres de permisos completo
    """
    role_perms = get_user_role_permissions(session, user_id)
    extra_perms = get_user_extra_permissions(session, user_id)
    return role_perms | extra_perms


def has_permission(session: Session, user_id: str, permission_name: str) -> bool:
    """
    Verifica si un usuario tiene un permiso específico.
    
    Args:
        session: Sesión de BD
        user_id: ID del usuario
        permission_name: Nombre del permiso (ej: 'create_job')
    
    Returns:
        True si el usuario tiene el permiso
    """
    user_perms = get_user_permissions(session, user_id)
    return permission_name in user_perms


def can_access_resource(
    session: Session,
    user_id: str,
    resource_type: str,
    resource_id: str,
    action: str = "read",
) -> bool:
    """
    Verifica si un usuario puede acceder a un recurso específico.
    
    Lógica:
    1. Si el usuario es ADMIN, tiene acceso total
    2. Si hay una entrada en resource_access, verificar access_level
    3. Sino, retornar False (no tiene acceso)
    
    Args:
        session: Sesión de BD
        user_id: ID del usuario
        resource_type: Tipo de recurso (job, team, report, etc.)
        resource_id: ID del recurso específico
        action: Acción a realizar (read, write, admin)
    
    Returns:
        True si puede acceder
    """
    user = session.get(UserORM, user_id)
    if not user:
        return False
    
    # Admin tiene acceso total
    if user.role == RoleType.ADMIN.value:
        return True
    
    # Verificar si hay acceso específico al recurso
    access_record = session.query(ResourceAccessORM).filter(
        and_(
            ResourceAccessORM.user_id == user_id,
            ResourceAccessORM.resource_type == resource_type,
            ResourceAccessORM.resource_id == resource_id,
            # Filtrar accesos expirados
            (ResourceAccessORM.expires_at.is_(None) | (ResourceAccessORM.expires_at > time.time()))
        )
    ).first()
    
    if not access_record:
        return False
    
    # Verificar que el nivel de acceso sea suficiente para la acción
    required_access_levels = {
        "read": [AccessLevel.READ.value, AccessLevel.WRITE.value, AccessLevel.ADMIN.value],
        "write": [AccessLevel.WRITE.value, AccessLevel.ADMIN.value],
        "admin": [AccessLevel.ADMIN.value],
    }
    
    return access_record.access_level in required_access_levels.get(action, [])


def grant_permission_to_user(
    session: Session,
    user_id: str,
    permission_id: str,
    granted_by_user_id: str,
    expires_at: Optional[float] = None,
) -> None:
    """
    Asigna un permiso específico a un usuario.
    
    Args:
        session: Sesión de BD
        user_id: ID del usuario que recibirá el permiso
        permission_id: ID del permiso
        granted_by_user_id: ID del usuario que otorga el permiso (para auditoría)
        expires_at: Unix timestamp cuando expira el permiso (None = nunca)
    """
    perm = UserPermissionORM(
        id=str(uuid4()),
        user_id=user_id,
        permission_id=permission_id,
        granted_by=granted_by_user_id,
        expires_at=expires_at,
    )
    session.add(perm)
    session.commit()


def revoke_permission_from_user(
    session: Session,
    user_id: str,
    permission_id: str,
) -> bool:
    """
    Revoca un permiso de un usuario.
    
    Returns:
        True si se revocó, False si no existía
    """
    perm = session.query(UserPermissionORM).filter(
        and_(
            UserPermissionORM.user_id == user_id,
            UserPermissionORM.permission_id == permission_id
        )
    ).first()
    
    if not perm:
        return False
    
    session.delete(perm)
    session.commit()
    return True


def grant_resource_access(
    session: Session,
    user_id: str,
    resource_type: str,
    resource_id: str,
    access_level: str,
    assigned_by_user_id: str,
    expires_at: Optional[float] = None,
) -> None:
    """
    Otorga acceso a un recurso específico a un usuario.
    
    Args:
        session: Sesión de BD
        user_id: ID del usuario
        resource_type: Tipo de recurso (job, team, report)
        resource_id: ID del recurso
        access_level: 'read', 'write', o 'admin'
        assigned_by_user_id: ID del usuario que asigna (para auditoría)
        expires_at: Unix timestamp cuando expira el acceso
    """
    # Si ya existe, actualizar; sino, crear
    existing = session.query(ResourceAccessORM).filter(
        and_(
            ResourceAccessORM.user_id == user_id,
            ResourceAccessORM.resource_type == resource_type,
            ResourceAccessORM.resource_id == resource_id,
        )
    ).first()
    
    if existing:
        existing.access_level = access_level
        existing.expires_at = expires_at
    else:
        access = ResourceAccessORM(
            id=str(uuid4()),
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            access_level=access_level,
            assigned_by=assigned_by_user_id,
            expires_at=expires_at,
        )
        session.add(access)
    
    session.commit()


def revoke_resource_access(
    session: Session,
    user_id: str,
    resource_type: str,
    resource_id: str,
) -> bool:
    """
    Revoca el acceso a un recurso específico.
    
    Returns:
        True si se revocó, False si no existía
    """
    access = session.query(ResourceAccessORM).filter(
        and_(
            ResourceAccessORM.user_id == user_id,
            ResourceAccessORM.resource_type == resource_type,
            ResourceAccessORM.resource_id == resource_id,
        )
    ).first()
    
    if not access:
        return False
    
    session.delete(access)
    session.commit()
    return True


def log_audit_event(
    session: Session,
    action: str,
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    ip_address: Optional[str] = None,
    status: str = "success",
    error_message: Optional[str] = None,
) -> None:
    """
    Registra un evento en el log de auditoría.
    
    Args:
        session: Sesión de BD
        action: Acción realizada (ej: 'job_created', 'user_permission_granted')
        user_id: ID del usuario que realizó la acción
        resource_type: Tipo de recurso afectado
        resource_id: ID del recurso afectado
        old_value: Valores anteriores (para updates)
        new_value: Valores nuevos (para updates)
        ip_address: IP del cliente
        status: 'success' o 'failed'
        error_message: Mensaje de error si falló
    """
    log_entry = AuditLogORM(
        id=str(uuid4()),
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
        status=status,
        error_message=error_message,
    )
    session.add(log_entry)
    session.commit()


def create_default_permissions(session: Session) -> None:
    """
    Crea los permisos por defecto del sistema.
    Se ejecuta una sola vez en la inicialización.
    """
    # Verificar si ya existen
    if session.query(PermissionORM).first():
        return
    
    permissions_to_create = [
        # Permisos de Jobs
        PermissionORM(
            id=str(uuid4()),
            name="create_job",
            display_name="Crear Trabajo",
            description="Crear nuevo trabajo de procesamiento",
            resource_type="job",
            action="create",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="read_job",
            display_name="Ver Trabajo",
            description="Ver detalles de un trabajo",
            resource_type="job",
            action="read",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="update_job",
            display_name="Actualizar Trabajo",
            description="Modificar un trabajo",
            resource_type="job",
            action="update",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="delete_job",
            display_name="Eliminar Trabajo",
            description="Eliminar un trabajo",
            resource_type="job",
            action="delete",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="process_job",
            display_name="Procesar Trabajo",
            description="Procesar PDF (OCR, validación)",
            resource_type="job",
            action="process",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="review_job",
            display_name="Revisar Trabajo",
            description="Realizar revisión manual",
            resource_type="job",
            action="review",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="approve_job",
            display_name="Aprobar Trabajo",
            description="Aprobar resultado final",
            resource_type="job",
            action="approve",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="export_jobs",
            display_name="Exportar Trabajos",
            description="Exportar datos de trabajos",
            resource_type="job",
            action="export",
        ),
        # Permisos de Usuarios
        PermissionORM(
            id=str(uuid4()),
            name="create_user",
            display_name="Crear Usuario",
            description="Crear nuevo usuario",
            resource_type="user",
            action="create",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="read_user",
            display_name="Ver Usuario",
            description="Ver datos de usuario",
            resource_type="user",
            action="read",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="update_user",
            display_name="Actualizar Usuario",
            description="Modificar datos de usuario",
            resource_type="user",
            action="update",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="delete_user",
            display_name="Eliminar Usuario",
            description="Eliminar usuario del sistema",
            resource_type="user",
            action="delete",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="grant_permission",
            display_name="Otorgar Permiso",
            description="Asignar permisos a usuarios",
            resource_type="user",
            action="update",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="revoke_permission",
            display_name="Revocar Permiso",
            description="Remover permisos de usuarios",
            resource_type="user",
            action="update",
        ),
        # Permisos de Equipos
        PermissionORM(
            id=str(uuid4()),
            name="create_team",
            display_name="Crear Equipo",
            description="Crear nuevo equipo/departamento",
            resource_type="team",
            action="create",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="read_team",
            display_name="Ver Equipo",
            description="Ver datos del equipo",
            resource_type="team",
            action="read",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="update_team",
            display_name="Actualizar Equipo",
            description="Modificar datos del equipo",
            resource_type="team",
            action="update",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="delete_team",
            display_name="Eliminar Equipo",
            description="Eliminar equipo",
            resource_type="team",
            action="delete",
        ),
        # Permisos de Reportes
        PermissionORM(
            id=str(uuid4()),
            name="read_report",
            display_name="Ver Reportes",
            description="Ver reportes del sistema",
            resource_type="report",
            action="read",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="create_report",
            display_name="Crear Reportes",
            description="Generar nuevos reportes",
            resource_type="report",
            action="create",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="export_report",
            display_name="Exportar Reportes",
            description="Exportar reportes",
            resource_type="report",
            action="export",
        ),
        # Permisos de Auditoría
        PermissionORM(
            id=str(uuid4()),
            name="read_audit_log",
            display_name="Ver Auditoría",
            description="Ver logs de auditoría",
            resource_type="audit_log",
            action="read",
        ),
        PermissionORM(
            id=str(uuid4()),
            name="export_audit_log",
            display_name="Exportar Auditoría",
            description="Exportar logs de auditoría",
            resource_type="audit_log",
            action="export",
        ),
        # Permisos de Importación
        PermissionORM(
            id=str(uuid4()),
            name="import_formative_actions",
            display_name="Importar Acciones Formativas",
            description="Importar datos de acciones formativas",
            resource_type="formative_action",
            action="import",
        ),
    ]
    
    for perm in permissions_to_create:
        session.add(perm)
    
    session.commit()


def create_default_roles(session: Session) -> None:
    """
    Crea los roles por defecto del sistema con sus permisos asociados.
    Se ejecuta una sola vez en la inicialización.
    """
    from packages.domain.permissions_enums import ROLE_PERMISSIONS
    
    # Verificar si ya existen
    if session.query(RoleORM).first():
        return
    
    role_definitions = [
        ("admin", "Administrador", "Control total del sistema"),
        ("supervisor", "Supervisor", "Supervisa equipos y validaciones"),
        ("analyst", "Analista", "Revisa y valida documentos"),
        ("dba", "Operador de BD", "Mantenimiento de base de datos"),
    ]
    
    for role_name, display_name, description in role_definitions:
        role = RoleORM(
            name=role_name,
            display_name=display_name,
            description=description,
            is_system_role=True,
        )
        session.add(role)
    
    session.commit()
    
    # Asignar permisos a roles
    for role_name, permission_names in ROLE_PERMISSIONS.items():
        for perm_name in permission_names:
            permission = session.query(PermissionORM).filter(
                PermissionORM.name == perm_name
            ).first()
            
            if permission:
                role_perm = RolePermissionORM(
                    id=str(uuid4()),
                    role_name=role_name,
                    permission_id=permission.id,
                )
                session.add(role_perm)
    
    session.commit()
