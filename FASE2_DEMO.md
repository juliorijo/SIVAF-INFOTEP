# SIVAF Fase 2 - Sistema Multi-usuario en Vivo

## 🚀 Estado Actual

El servidor SIVAF está **corriendo en http://localhost:8000** con:

✅ Sistema de permisos granulares (8 permisos x 4 roles)
✅ 4 usuarios de prueba con roles diferentes  
✅ API REST completa (Fase 2) con endpoints de gestión
✅ Auditoría completa de acciones
✅ Control de acceso basado en roles (RBAC)

---

## 📊 Acceder al Sistema

### Opción 1: Dashboard Interactivo (Recomendado)

Abre en tu navegador: **`live_dashboard.html`** (en este repositorio)

Este archivo HTML muestra:
- Dashboards personalizados por rol
- Permisos específicos de cada rol
- Gestión de usuarios y equipos
- Registro de auditoría
- Interfaz interactiva para cambiar roles

---

### Opción 2: API Rest Completa

**Base URL:** `http://localhost:8000`

#### Documentación Interactiva:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

#### Usuarios de Prueba:

```
Admin:       admin_test / admin123_password_long
Supervisor:  supervisor_test / supervisor123_password_long
Analyst:     analyst_test / analyst123_password_long
DBA:         dba_test / dba123_password_long
```

---

## 📋 Endpoints Implementados (Fase 2)

### Autenticación
```
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/me
```

### Usuarios
```
GET    /api/v1/users               (Admin: todos, Supervisor: equipo)
POST   /api/v1/users               (Admin only)
GET    /api/v1/users/{user_id}     (Usuarios: propios, Admin: todos)
PUT    /api/v1/users/{user_id}     (Admin o propios)
```

### Permisos
```
GET    /api/v1/permissions         (Listar permisos disponibles)
GET    /api/v1/users/{user_id}/permissions
POST   /api/v1/users/{user_id}/permissions        (Otorgar)
DELETE /api/v1/users/{user_id}/permissions/{perm} (Revocar)
```

### Equipos
```
GET    /api/v1/teams               (Admin: todos, Others: propio equipo)
POST   /api/v1/teams               (Admin only)
POST   /api/v1/teams/{team_id}/members
```

### Acceso a Recursos
```
POST   /api/v1/resource-access
DELETE /api/v1/resource-access/{user_id}/{type}/{id}
```

### Auditoría
```
GET    /api/v1/audit-log           (Según rol)
```

### Dashboard
```
GET    /api/v1/dashboard           (Personalizado por rol)
```

---

## 🔐 Control de Acceso por Rol

### 👑 ADMIN (Control Total)
```
✅ Ver/crear/editar/eliminar usuarios
✅ Otorgar y revocar permisos
✅ Gestionar equipos
✅ Ver auditoría completa
✅ Acceso a backups
✅ Configurar OCR
```

### 🎯 SUPERVISOR (Equipo)
```
✅ Ver usuarios del equipo
✅ Ver trabajos del equipo
✅ Asignar tareas
✅ Ver auditoría del equipo
✅ Generar reportes
❌ No puede crear/eliminar usuarios
❌ No puede modificar permisos
```

### 📊 ANALYST (Personal)
```
✅ Ver documentos propios
✅ Procesar documentos
✅ Cargar PDFs
✅ Crear reportes
❌ No puede ver otros usuarios
❌ No puede acceder a auditoría
```

### 🛠️ DBA (Mantenimiento)
```
✅ Backup & Restore
✅ Gestionar migraciones
✅ Monitorear BD
✅ Ver logs de sistema
❌ No puede acceder a aplicación
❌ No puede modificar datos
```

---

## 📊 Características Implementadas

### 1. Permisos Granulares (8 Acciones)
- USUARIOS: crear, editar, eliminar, suspender
- PERMISOS: otorgar, revocar
- RECURSOS: acceso a datos específicos
- AUDITORÍA: ver logs

### 2. Roles Predefinidos (4)
- **Admin:** Todos los permisos
- **Supervisor:** Gestión de equipo
- **Analyst:** Datos personales
- **DBA:** Mantenimiento

### 3. Auditoría Completa
```
Acciones registradas:
- Logins/Logouts
- Creación/edición de usuarios
- Otorgamiento/revocación de permisos
- Acceso a recursos
- Cambios de configuración
```

### 4. Control de Recursos
```
Por PDF/Documento:
- usuario_id + resource_type + resource_id
- access_level (read/write/admin)
- expires_at (permisos temporales)
```

### 5. Seguridad
```
✅ Hashing de contraseñas (PBKDF2, 600k iteraciones)
✅ Sesiones HTTP-only
✅ 8 horas de expiración
✅ Validación de permisos en cada endpoint
✅ Auditoría de intentos fallidos
```

---

## 🗄️ Estructura de BD

### Tablas de Fase 1 (Permisos)
```
teams                    - Equipos/departamentos
team_members            - Membresía en equipos
roles                   - Admin, Supervisor, Analyst, DBA
permissions             - Acciones (create_user, delete_user, etc.)
role_permissions        - Matriz rol->permisos
user_permissions        - Permisos adicionales por usuario
resource_access         - Acceso granular a PDFs/recursos
audit_log               - Registro de auditoría completo
```

### Tablas Originales (Intactas)
```
processing_jobs         - Trabajos de procesamiento
roster_data             - Datos de nóminas
document_verifications  - Verificaciones de documentos
user_sessions          - Sesiones activas
```

---

## 🎯 Próximos Pasos (Fase 3+)

### Fase 3: OCR Mejorado
- [ ] Integración con PaddleOCR
- [ ] Mejor detección de documentos
- [ ] Validación automática
- [ ] Fallback a Tesseract

### Fase 4: Panel DBA
- [ ] Dashboard de backups
- [ ] Import/Export de datos
- [ ] Estadísticas de BD
- [ ] Alertas de rendimiento

### Fase 5: Versionamiento de BD
- [ ] Alembic migrations
- [ ] CHANGELOG de esquema
- [ ] Upgrade/downgrade scripts
- [ ] Validación de versiones

### Fase 6: Frontend Web
- [ ] UI con Tailwind CSS
- [ ] Dashboards por rol
- [ ] Gestión de usuarios
- [ ] Vista en tiempo real

---

## 📝 Pruebas Rápidas

### Test 1: Login y Dashboard
```bash
# Iniciar sesión como admin
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin_test","password":"admin123_password_long"}'

# Ver dashboard
curl http://localhost:8000/api/v1/dashboard \
  -H "Cookie: sivaf_session=<token>"
```

### Test 2: Ver Permisos
```bash
curl http://localhost:8000/api/v1/permissions \
  -H "Cookie: sivaf_session=<token>"
```

### Test 3: Auditoría
```bash
curl http://localhost:8000/api/v1/audit-log \
  -H "Cookie: sivaf_session=<token>"
```

---

## 🐛 Troubleshooting

### Puerto 8000 no responde
```bash
# Verificar que el servidor esté corriendo
ps aux | grep "python run_dev_server.py"

# Si no está, reiniciar:
cd sivaf-repo
python run_dev_server.py
```

### Base de datos corrupta
```bash
# Limpiar y reiniciar
rm -f infotep.db
python run_dev_server.py
```

### Problemas con imports
```bash
# Reinstalar dependencias
pip install -r requirements.txt
python run_dev_server.py
```

---

## 📦 Archivos Clave

```
sivaf-repo/
├── apps/api/
│   ├── main.py                    # Servidor FastAPI principal
│   ├── routes_phase2.py          # Endpoints de Fase 2
│   ├── permissions.py            # Lógica de autorización
│   ├── models_permissions.py     # ORM de permisos
│   ├── dependencies.py           # Autenticación/autorización
│   ├── database.py               # ORM y conexión
│   └── schemas_phase2.py         # Pydantic schemas
│
├── packages/domain/
│   └── permissions_enums.py      # Enums (roles, permisos, etc.)
│
├── infrastructure/database/
│   └── 001_add_permissions_tables.sql  # Migraciones
│
├── run_dev_server.py             # Script de inicio
├── live_dashboard.html           # Dashboard interactivo
├── .env.local                    # Variables de entorno (SQLite)
└── requirements.txt              # Dependencias Python
```

---

## ✨ Características Destacadas

### 🎨 Multi-rol
Cada usuario ve solo lo que puede acceder según su rol

### 🔐 Granular
Permisos a nivel de acción y recurso

### 📊 Auditoría
Cada acción es registrada con usuario, timestamp, detalles

### ⚡ Rápida
SQLite para desarrollo, fácil migrar a PostgreSQL

### 🧪 Testeable
Tests incluidos para validar permisos

### 🚀 Escalable
Arquitectura lista para producción (PostgreSQL + Redis)

---

## 📞 Contacto & Soporte

Para más información sobre SIVAF:
- GitHub: [juliorijo/SIVAF-INFOTEP](https://github.com/juliorijo/SIVAF-INFOTEP)
- Documentación: Ver `DESIGN.md` y `README.md` en el repo

---

**¡Sistema listo! 🎉 Abre `live_dashboard.html` para ver el sistema en acción.**
