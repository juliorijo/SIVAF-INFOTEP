"""
Tests para la lógica de permisos y autorización.
Fase 1: Permisos granulares & Multi-usuario
"""

import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta
import time

from apps.api.database import SessionLocal, UserORM, init_db
from apps.api.permissions import (
    has_permission,
    can_access_resource,
    grant_permission_to_user,
    revoke_permission_from_user,
    grant_resource_access,
    revoke_resource_access,
    log_audit_event,
    get_user_permissions,
    create_default_permissions,
    create_default_roles,
)
from apps.api.models_permissions import (
    PermissionORM,
    RoleORM,
    RolePermissionORM,
    TeamORM,
    TeamMemberORM,
    ResourceAccessORM,
    AuditLogORM,
)
from packages.domain.permissions_enums import RoleType, AuditAction


@pytest.fixture(scope="session")
def db_setup():
    """Inicializa la BD para tests."""
    init_db()
    
    # Limpiar datos anteriores
    session = SessionLocal()
    session.query(AuditLogORM).delete()
    session.query(ResourceAccessORM).delete()
    session.query(RolePermissionORM).delete()
    session.query(PermissionORM).delete()
    session.query(RoleORM).delete()
    session.query(UserORM).delete()
    session.commit()
    
    # Crear roles y permisos por defecto
    create_default_roles(session)
    create_default_permissions(session)
    session.commit()
    session.close()
    
    yield


@pytest.fixture
def session(db_setup):
    """Proporciona una sesión limpia para cada test."""
    _session = SessionLocal()
    yield _session
    _session.close()


@pytest.fixture
def admin_user(session):
    """Crea un usuario admin para tests."""
    user = UserORM(
        id=str(uuid4()),
        username="admin_test",
        password_hash="dummy_hash",
        role=RoleType.ADMIN.value,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def analyst_user(session):
    """Crea un usuario analista para tests."""
    user = UserORM(
        id=str(uuid4()),
        username="analyst_test",
        password_hash="dummy_hash",
        role=RoleType.ANALYST.value,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def supervisor_user(session):
    """Crea un usuario supervisor para tests."""
    user = UserORM(
        id=str(uuid4()),
        username="supervisor_test",
        password_hash="dummy_hash",
        role=RoleType.SUPERVISOR.value,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


class TestPermissionModel:
    """Tests para el modelo de permisos."""
    
    def test_admin_tiene_permisos(self, session, admin_user):
        """Test: Admin debe tener permisos de create_job."""
        assert has_permission(session, admin_user.id, "create_job") is True
        
    def test_admin_tiene_todos_permisos(self, session, admin_user):
        """Test: Admin debe tener todos los permisos."""
        permisos = get_user_permissions(session, admin_user.id)
        assert "create_job" in permisos
        assert "read_job" in permisos
        assert "update_job" in permisos
        assert "delete_job" in permisos
        assert "create_user" in permisos
        assert len(permisos) > 10  # Debe tener muchos permisos
    
    def test_analyst_tiene_permisos_limitados(self, session, analyst_user):
        """Test: Analyst solo debe tener permisos de lectura/proceso."""
        assert has_permission(session, analyst_user.id, "read_job") is True
        assert has_permission(session, analyst_user.id, "process_job") is True
        assert has_permission(session, analyst_user.id, "create_user") is False
        assert has_permission(session, analyst_user.id, "delete_job") is False
    
    def test_supervisor_tiene_permisos_equipo(self, session, supervisor_user):
        """Test: Supervisor debe poder revisar trabajos."""
        assert has_permission(session, supervisor_user.id, "review_job") is True
        assert has_permission(session, supervisor_user.id, "create_user") is False


class TestResourceAccess:
    """Tests para control de acceso a recursos específicos."""
    
    def test_admin_acceso_total_recurso(self, session, admin_user):
        """Test: Admin accede a cualquier recurso."""
        job_id = str(uuid4())
        assert can_access_resource(session, admin_user.id, "job", job_id, "read") is True
        assert can_access_resource(session, admin_user.id, "job", job_id, "write") is True
        assert can_access_resource(session, admin_user.id, "job", job_id, "admin") is True
    
    def test_usuario_sin_acceso_recurso(self, session, analyst_user):
        """Test: Usuario sin acceso a recurso no puede acceder."""
        job_id = str(uuid4())
        assert can_access_resource(session, analyst_user.id, "job", job_id, "read") is False
    
    def test_grant_y_revoke_acceso_recurso(self, session, admin_user, analyst_user):
        """Test: Otorgar y revocar acceso a recurso específico."""
        job_id = str(uuid4())
        
        # Inicialmente no tiene acceso
        assert can_access_resource(session, analyst_user.id, "job", job_id, "read") is False
        
        # Otorgar acceso
        grant_resource_access(
            session, analyst_user.id, "job", job_id, "read", admin_user.id
        )
        
        # Ahora tiene acceso de lectura
        assert can_access_resource(session, analyst_user.id, "job", job_id, "read") is True
        
        # Pero no tiene acceso de escritura
        assert can_access_resource(session, analyst_user.id, "job", job_id, "write") is False
        
        # Revocar acceso
        revoke_resource_access(session, analyst_user.id, "job", job_id)
        
        # Ya no tiene acceso
        assert can_access_resource(session, analyst_user.id, "job", job_id, "read") is False


class TestPermissionGrantRevoke:
    """Tests para otorgar/revocar permisos a usuarios."""
    
    def test_grant_permission_to_user(self, session, admin_user, analyst_user):
        """Test: Otorgar permiso adicional a usuario."""
        # Analyst inicialmente no puede crear usuarios
        assert has_permission(session, analyst_user.id, "create_user") is False
        
        # Obtener el ID del permiso
        perm = session.query(PermissionORM).filter(
            PermissionORM.name == "create_user"
        ).first()
        
        if perm:
            # Otorgar permiso
            grant_permission_to_user(
                session, analyst_user.id, perm.id, admin_user.id
            )
            
            # Ahora sí puede crear usuarios
            assert has_permission(session, analyst_user.id, "create_user") is True
    
    def test_revoke_permission_from_user(self, session, admin_user, analyst_user):
        """Test: Revocar permiso de usuario."""
        # Obtener el ID del permiso
        perm = session.query(PermissionORM).filter(
            PermissionORM.name == "create_user"
        ).first()
        
        if perm:
            # Otorgar permiso
            grant_permission_to_user(
                session, analyst_user.id, perm.id, admin_user.id
            )
            assert has_permission(session, analyst_user.id, "create_user") is True
            
            # Revocar permiso
            success = revoke_permission_from_user(
                session, analyst_user.id, perm.id
            )
            assert success is True
            
            # Ya no tiene permiso
            assert has_permission(session, analyst_user.id, "create_user") is False


class TestAuditLog:
    """Tests para el log de auditoría."""
    
    def test_log_audit_event_success(self, session, admin_user):
        """Test: Registrar evento exitoso en auditoría."""
        log_audit_event(
            session,
            action=AuditAction.USER_CREATED.value,
            user_id=admin_user.id,
            resource_type="user",
            resource_id=str(uuid4()),
            new_value={"username": "newuser"},
            status="success",
        )
        
        # Verificar que se guardó
        logs = session.query(AuditLogORM).filter(
            AuditLogORM.user_id == admin_user.id
        ).all()
        assert len(logs) > 0
        assert logs[0].action == AuditAction.USER_CREATED.value
        assert logs[0].status == "success"
    
    def test_log_audit_event_failure(self, session, admin_user):
        """Test: Registrar evento fallido en auditoría."""
        log_audit_event(
            session,
            action="invalid_action",
            user_id=admin_user.id,
            status="failed",
            error_message="Permission denied",
        )
        
        logs = session.query(AuditLogORM).filter(
            AuditLogORM.status == "failed"
        ).all()
        assert len(logs) > 0
        assert logs[0].error_message == "Permission denied"


class TestTeamModel:
    """Tests para equipos/departamentos."""
    
    def test_create_team(self, session, admin_user):
        """Test: Crear un equipo."""
        team = TeamORM(
            id=str(uuid4()),
            name="Equipo Validación",
            description="Equipo encargado de validar PDFs",
            manager_id=admin_user.id,
        )
        session.add(team)
        session.commit()
        
        # Verificar que se creó
        retrieved = session.query(TeamORM).filter(
            TeamORM.name == "Equipo Validación"
        ).first()
        assert retrieved is not None
        assert retrieved.manager_id == admin_user.id
    
    def test_add_user_to_team(self, session, admin_user, analyst_user):
        """Test: Agregar usuario a equipo."""
        team = TeamORM(
            id=str(uuid4()),
            name="Equipo Test",
            manager_id=admin_user.id,
        )
        session.add(team)
        session.commit()
        
        member = TeamMemberORM(
            id=str(uuid4()),
            team_id=team.id,
            user_id=analyst_user.id,
            role_in_team="member",
        )
        session.add(member)
        session.commit()
        
        # Verificar
        members = session.query(TeamMemberORM).filter(
            TeamMemberORM.team_id == team.id
        ).all()
        assert len(members) == 1
        assert members[0].user_id == analyst_user.id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
