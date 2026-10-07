from enum import Enum


class RoleType(str, Enum):
    """Roles del sistema SIVAF."""
    ADMIN = "admin"  # Control total del sistema
    SUPERVISOR = "supervisor"  # Supervisa equipos/departamentos
    ANALYST = "analyst"  # Analista que revisa PDFs
    DBA = "dba"  # Operador de base de datos (mantenimiento)


class PermissionAction(str, Enum):
    """Acciones granulares permitidas en recursos."""
    CREATE = "create"  # Crear nuevo recurso
    READ = "read"  # Ver/leer recurso
    UPDATE = "update"  # Modificar recurso
    DELETE = "delete"  # Eliminar recurso
    EXPORT = "export"  # Exportar datos
    IMPORT = "import"  # Importar datos
    REVIEW = "review"  # Revisar manualmente
    APPROVE = "approve"  # Aprobar acción
    PROCESS = "process"  # Procesar PDF


class ResourceType(str, Enum):
    """Tipos de recursos en el sistema."""
    JOB = "job"  # Trabajo de procesamiento (PDF)
    USER = "user"  # Usuario del sistema
    TEAM = "team"  # Equipo/Departamento
    REPORT = "report"  # Reportes
    AUDIT_LOG = "audit_log"  # Logs de auditoría
    FORMATIVE_ACTION = "formative_action"  # Acciones formativas
    VALIDATION_RESULT = "validation_result"  # Resultados de validación


class AccessLevel(str, Enum):
    """Niveles de acceso a recursos específicos."""
    READ = "read"  # Solo lectura
    WRITE = "write"  # Lectura y escritura
    ADMIN = "admin"  # Control total


class UserStatus(str, Enum):
    """Estados de los usuarios."""
    ACTIVE = "active"  # Usuario activo
    SUSPENDED = "suspended"  # Usuario suspendido temporalmente
    INACTIVE = "inactive"  # Usuario inactivo (archivado)


class AuditAction(str, Enum):
    """Acciones registradas en auditoría."""
    # Autenticación
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"

    # Gestión de usuarios
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    USER_ROLE_CHANGED = "user_role_changed"
    USER_PERMISSION_GRANTED = "user_permission_granted"
    USER_PERMISSION_REVOKED = "user_permission_revoked"

    # Gestión de equipos
    TEAM_CREATED = "team_created"
    TEAM_UPDATED = "team_updated"
    TEAM_DELETED = "team_deleted"
    USER_ADDED_TO_TEAM = "user_added_to_team"
    USER_REMOVED_FROM_TEAM = "user_removed_from_team"

    # Procesamiento de PDFs
    JOB_CREATED = "job_created"
    JOB_PROCESSED = "job_processed"
    JOB_REVIEWED = "job_reviewed"
    JOB_FAILED = "job_failed"
    JOB_DELETED = "job_deleted"

    # Importación
    FORMATIVE_ACTIONS_IMPORTED = "formative_actions_imported"
    IMPORT_FAILED = "import_failed"

    # Acceso a recursos
    RESOURCE_ACCESS_GRANTED = "resource_access_granted"
    RESOURCE_ACCESS_REVOKED = "resource_access_revoked"

    # Datos
    DATA_EXPORTED = "data_exported"
    BACKUP_CREATED = "backup_created"
    MIGRATION_EXECUTED = "migration_executed"

    # Auditoría
    AUDIT_LOG_VIEWED = "audit_log_viewed"


class PermissionScope(str, Enum):
    """Scope en el que aplica un permiso."""
    SYSTEM = "system"  # A nivel de sistema (admin solo)
    TEAM = "team"  # A nivel de equipo
    USER = "user"  # A nivel de usuario (propio recurso)


# Pre-defined permission matrices for roles
ROLE_PERMISSIONS = {
    RoleType.ADMIN.value: [
        # Admin tiene acceso total a todo
        "create_job", "read_job", "update_job", "delete_job", "process_job", "review_job", "approve_job", "export_jobs",
        "create_user", "read_user", "update_user", "delete_user", "grant_permission", "revoke_permission",
        "create_team", "read_team", "update_team", "delete_team",
        "import_formative_actions",
        "read_audit_log", "export_audit_log",
        "create_report", "read_report", "export_report",
    ],
    RoleType.SUPERVISOR.value: [
        # Supervisor ve su equipo + propios
        "read_job",  # Solo sus asignados
        "process_job",  # Puede procesar
        "review_job",  # Puede revisar
        "read_user",  # Ver miembros de su equipo
        "read_team",  # Ver su equipo
        "read_audit_log",  # Ver auditoría de su equipo
        "read_report",  # Ver reportes
        "export_report",  # Exportar reportes
    ],
    RoleType.ANALYST.value: [
        # Analyst solo ve sus PDFs asignados
        "read_job",  # Solo sus jobs
        "process_job",  # Procesar sus jobs
        "review_job",  # Revisar sus jobs
        "read_report",  # Ver reportes (filtrados)
    ],
    RoleType.DBA.value: [
        # DBA mantenimiento de BD
        "read_audit_log",  # Ver auditoría
        "read_report",  # Ver reportes del sistema
        "export_report",  # Exportar datos
        # Sin acceso a PDFs, usuarios, equipos
    ],
}
