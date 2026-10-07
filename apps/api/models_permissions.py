from __future__ import annotations

"""
Compat layer for permission models.

These models live in apps.api.database so all ORM mappers share the same Base/metadata.
Keeping this module avoids touching existing imports across the codebase.
"""

from apps.api.database import (
    AuditLogORM,
    PermissionORM,
    ResourceAccessORM,
    RoleORM,
    RolePermissionORM,
    TeamMemberORM,
    TeamORM,
    UserPermissionORM,
)

__all__ = [
    "AuditLogORM",
    "PermissionORM",
    "ResourceAccessORM",
    "RoleORM",
    "RolePermissionORM",
    "TeamMemberORM",
    "TeamORM",
    "UserPermissionORM",
]
