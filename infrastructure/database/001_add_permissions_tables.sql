-- Migración 001: Agregar tablas de permisos y control de acceso
-- Este script crea la estructura de permisos granulares para Fase 1

-- 1. Crear tabla TEAMS (Equipos/Departamentos)
CREATE TABLE IF NOT EXISTS teams (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    manager_id VARCHAR(36),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (manager_id) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE(name)
);

CREATE INDEX IF NOT EXISTS idx_teams_manager_id ON teams(manager_id);
CREATE INDEX IF NOT EXISTS idx_teams_name ON teams(name);

-- 2. Crear tabla TEAM_MEMBERS (Membresía en equipos)
CREATE TABLE IF NOT EXISTS team_members (
    id VARCHAR(36) PRIMARY KEY,
    team_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    role_in_team VARCHAR(50) NOT NULL DEFAULT 'member',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(team_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_team_members_team_id ON team_members(team_id);
CREATE INDEX IF NOT EXISTS idx_team_members_user_id ON team_members(user_id);

-- 3. Crear tabla ROLES (Roles del sistema)
CREATE TABLE IF NOT EXISTS roles (
    name VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    is_system_role BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Insertar roles por defecto (admin, supervisor, analyst, dba)
INSERT INTO roles (name, display_name, description, is_system_role) VALUES
    ('admin', 'Administrador', 'Control total del sistema', TRUE),
    ('supervisor', 'Supervisor', 'Supervisa equipos y validaciones', TRUE),
    ('analyst', 'Analista', 'Revisa y valida documentos', TRUE),
    ('dba', 'Operador de BD', 'Mantenimiento de base de datos', TRUE)
ON CONFLICT (name) DO NOTHING;

-- 4. Crear tabla PERMISSIONS (Permisos granulares)
CREATE TABLE IF NOT EXISTS permissions (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(150) NOT NULL,
    description TEXT,
    resource_type VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_permission_name ON permissions(name);
CREATE INDEX IF NOT EXISTS idx_permission_resource_action ON permissions(resource_type, action);

-- 5. Crear tabla ROLE_PERMISSIONS (Mapeo roles → permisos)
CREATE TABLE IF NOT EXISTS role_permissions (
    id VARCHAR(36) PRIMARY KEY,
    role_name VARCHAR(50) NOT NULL,
    permission_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_name) REFERENCES roles(name) ON DELETE CASCADE,
    FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE,
    UNIQUE(role_name, permission_id)
);

CREATE INDEX IF NOT EXISTS idx_role_permissions_role_name ON role_permissions(role_name);
CREATE INDEX IF NOT EXISTS idx_role_permissions_permission_id ON role_permissions(permission_id);

-- 6. Crear tabla USER_PERMISSIONS (Permisos específicos por usuario)
CREATE TABLE IF NOT EXISTS user_permissions (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    permission_id VARCHAR(36) NOT NULL,
    granted_by VARCHAR(36),
    granted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE,
    FOREIGN KEY (granted_by) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE(user_id, permission_id)
);

CREATE INDEX IF NOT EXISTS idx_user_permissions_user_id ON user_permissions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_permissions_permission_id ON user_permissions(permission_id);
CREATE INDEX IF NOT EXISTS idx_user_permissions_granted_by ON user_permissions(granted_by);

-- 7. Crear tabla RESOURCE_ACCESS (Acceso a recursos específicos)
CREATE TABLE IF NOT EXISTS resource_access (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(36) NOT NULL,
    access_level VARCHAR(50) NOT NULL,
    assigned_by VARCHAR(36),
    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE(user_id, resource_type, resource_id)
);

CREATE INDEX IF NOT EXISTS idx_resource_access_user_id ON resource_access(user_id);
CREATE INDEX IF NOT EXISTS idx_resource_access_resource ON resource_access(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_resource_access_lookup ON resource_access(user_id, resource_type, resource_id);

-- 8. Crear tabla AUDIT_LOG (Auditoría detallada)
CREATE TABLE IF NOT EXISTS audit_log (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36),
    action VARCHAR(255) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(36),
    old_value JSONB,
    new_value JSONB,
    ip_address VARCHAR(50),
    status VARCHAR(50) NOT NULL DEFAULT 'success',
    error_message TEXT,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_timestamp ON audit_log(user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource_type, resource_id);

-- 9. Actualizar tabla USERS (agregar campos nuevos)
-- NOTA: Solo ejecutar si las columnas no existen (ALTER TABLE conservador)

ALTER TABLE users 
ADD COLUMN IF NOT EXISTS team_id VARCHAR(36) REFERENCES teams(id) ON DELETE SET NULL;

ALTER TABLE users 
ADD COLUMN IF NOT EXISTS department VARCHAR(255);

ALTER TABLE users 
ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'active';

CREATE INDEX IF NOT EXISTS idx_users_team_id ON users(team_id);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);

-- 10. Comentarios y documentación
COMMENT ON TABLE teams IS 'Equipos/departamentos para agrupar usuarios y recursos';
COMMENT ON TABLE team_members IS 'Membresía de usuarios en equipos';
COMMENT ON TABLE roles IS 'Roles del sistema: admin, supervisor, analyst, dba';
COMMENT ON TABLE permissions IS 'Permisos granulares del sistema';
COMMENT ON TABLE role_permissions IS 'Mapeo de roles a permisos';
COMMENT ON TABLE user_permissions IS 'Permisos específicos asignados a usuarios (override)';
COMMENT ON TABLE resource_access IS 'Control de acceso a recursos específicos (PDFs, reportes, etc)';
COMMENT ON TABLE audit_log IS 'Log de auditoría: registro de todas las acciones del sistema';
