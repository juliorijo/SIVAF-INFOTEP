from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class TeamORM(Base):
    """
    Equipos/Departamentos para agrupar usuarios.
    Ejemplo: Departamento de Validación, Equipo 1, etc.
    """
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class TeamMemberORM(Base):
    """
    Membresía de usuarios en equipos.
    Un usuario puede pertenecer a múltiples equipos.
    """
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_in_team: Mapped[str] = mapped_column(String(50), default="member", nullable=False)  # 'member', 'lead'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class RoleORM(Base):
    """
    Roles del sistema: admin, supervisor, analyst, dba.
    Cada rol tiene un conjunto de permisos predefinidos.
    """
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)  # 'admin', 'supervisor', 'analyst', 'dba'
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # No se puede eliminar si es system
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class PermissionORM(Base):
    """
    Permisos granulares del sistema.
    Ejemplo: create_job, read_job, update_job, delete_job, export_data, import_data, review_job, approve_job.
    """
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'job', 'user', 'team', 'report', 'audit'
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # 'create', 'read', 'update', 'delete', 'export', 'import', 'review', 'approve'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_permission_resource_action", "resource_type", "action"),
    )


class RolePermissionORM(Base):
    """
    Mapeo de roles a permisos.
    Define qué permisos tiene cada rol (admin, supervisor, analyst, dba).
    """
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_name", "permission_id", name="uq_role_permission"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role_name: Mapped[str] = mapped_column(String(50), ForeignKey("roles.name", ondelete="CASCADE"), nullable=False, index=True)
    permission_id: Mapped[str] = mapped_column(String(36), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class UserPermissionORM(Base):
    """
    Permisos específicos asignados a usuarios.
    Permite override granular de permisos por usuario (ej: dar permiso extra a alguien).
    """
    __tablename__ = "user_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "permission_id", name="uq_user_permission"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    permission_id: Mapped[str] = mapped_column(String(36), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # Permiso temporal


class ResourceAccessORM(Base):
    """
    Control de acceso a recursos específicos.
    Ej: Usuario A solo puede ver PDFs asignados a él,
        Supervisor B solo ve PDFs de su equipo,
        Admin ve todos.
    """
    __tablename__ = "resource_access"
    __table_args__ = (
        UniqueConstraint("user_id", "resource_type", "resource_id", name="uq_user_resource_access"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'job', 'team', 'report'
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)  # ID del recurso (job_id, team_id, etc)
    access_level: Mapped[str] = mapped_column(String(50), nullable=False)  # 'read', 'write', 'admin'
    assigned_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # Acceso temporal

    __table_args__ = (
        Index("idx_resource_access_lookup", "user_id", "resource_type", "resource_id"),
    )


class AuditLogORM(Base):
    """
    Log de auditoría mejorado.
    Registra todas las acciones de usuarios en el sistema.
    """
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)  # 'login', 'logout', 'create_job', 'review_job', etc.
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 'job', 'user', 'team'
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # ID del recurso afectado
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # Valor anterior (para updates)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # Valor nuevo (para updates)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="success", nullable=False)  # 'success', 'failed'
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    __table_args__ = (
        Index("idx_audit_log_user_timestamp", "user_id", "timestamp"),
        Index("idx_audit_log_resource", "resource_type", "resource_id"),
    )
