#!/usr/bin/env python3
"""
Script para ejecutar el servidor de desarrollo con SQLite.
Inicializa la base de datos, crea permisos, roles y usuarios de prueba.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
env_file = Path(__file__).parent / '.env.local'
if env_file.exists():
    load_dotenv(env_file)
else:
    load_dotenv()

# Establecer DATABASE_URL a SQLite si no está configurado
if not os.getenv('DATABASE_URL'):
    db_path = Path(__file__).parent / 'infotep.db'
    os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'

print("[DB] Database: " + os.getenv('DATABASE_URL'))
print("[SECURE] Secure cookies: " + os.getenv('SIVAF_COOKIE_SECURE', 'false'))

# Importar después de configurar el entorno
from apps.api.database import SessionLocal, init_db
from apps.api.auth import hash_password
from apps.api.database import UserORM
from apps.api.models_permissions import TeamORM, RoleORM, PermissionORM
from apps.api.permissions import (
    create_default_permissions,
    create_default_roles,
)

def init_database():
    """Inicializar BD con tablas, permisos y datos de prueba."""
    print("\n[INIT] Inicializando base de datos...")
    
    # Crear tablas
    init_db()
    session = SessionLocal()
    
    try:
        # Crear permisos
        print("  [OK] Creando permisos...")
        create_default_permissions(session)
        
        # Crear roles
        print("  [OK] Creando roles...")
        create_default_roles(session)
        
        # Crear usuarios de prueba
        print("  [OK] Creando usuarios de prueba...")
        
        test_users = [
            {
                "username": "admin_test",
                "password": "admin123_password_long",
                "role": "admin",
                "department": "Administración"
            },
            {
                "username": "supervisor_test",
                "password": "supervisor123_password_long",
                "role": "supervisor",
                "department": "Supervisión"
            },
            {
                "username": "analyst_test",
                "password": "analyst123_password_long",
                "role": "analyst",
                "department": "Análisis"
            },
            {
                "username": "dba_test",
                "password": "dba123_password_long",
                "role": "dba",
                "department": "Base de Datos"
            },
        ]
        
        for user_data in test_users:
            # Verificar si usuario existe
            existing = session.query(UserORM).filter(
                UserORM.username == user_data["username"]
            ).first()
            
            if not existing:
                from uuid import uuid4
                user = UserORM(
                    id=str(uuid4()),
                    username=user_data["username"],
                    password_hash=hash_password(user_data["password"]),
                    role=user_data["role"],
                    department=user_data["department"],
                    status="active",
                    is_active=True,
                )
                session.add(user)
                print("    [USER] Usuario '" + user_data['username'] + "' creado (pwd: " + user_data['password'] + ")")
        
        session.commit()
        print("\n[SUCCESS] Base de datos inicializada correctamente!\n")
        
    except Exception as e:
        print("[ERROR] Error: " + str(e))
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    try:
        init_database()
        
        print("=" * 70)
        print("INICIANDO SERVIDOR DE DESARROLLO")
        print("=" * 70)
        print("\nUSUARIOS DE PRUEBA:")
        print("  Admin:       admin_test / admin123")
        print("  Supervisor:  supervisor_test / supervisor123")
        print("  Analyst:     analyst_test / analyst123")
        print("  DBA:         dba_test / dba123")
        print("\nURLs:")
        print("  API:        http://localhost:8000")
        print("  Docs:       http://localhost:8000/docs")
        print("  ReDoc:      http://localhost:8000/redoc")
        print("\nENDPOINTS DE FASE 2:")
        print("  GET    /api/v1/users")
        print("  POST   /api/v1/users")
        print("  GET    /api/v1/permissions")
        print("  GET    /api/v1/teams")
        print("  POST   /api/v1/teams")
        print("  POST   /api/v1/users/{user_id}/permissions")
        print("  DELETE /api/v1/users/{user_id}/permissions/{permission_id}")
        print("  GET    /api/v1/dashboard")
        print("  GET    /api/v1/audit-log")
        print("\nPara acceder, primero login en /api/v1/auth/login")
        print("=" * 70)
        print()
        
        # Iniciar servidor
        import uvicorn
        uvicorn.run(
            "apps.api.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info"
        )
        
    except KeyboardInterrupt:
        print("\n\nServidor detenido.")
        sys.exit(0)
    except Exception as e:
        print("\nError al iniciar servidor: " + str(e))
        sys.exit(1)
