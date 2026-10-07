# SIVAF — Sistema de Verificación de Acciones Formativas

Este proyecto representa la base inicial para una solución profesional de automatización de verificación documental de acciones formativas.

## Estado actual

El proyecto ya cuenta con una base de dominio, validación inicial y una API REST mínima para gestionar jobs de procesamiento documental.

## Módulos implementados

- `packages/domain`: entidades de negocio, enums y contratos base
- `packages/shared/normalization.py`: normalización de valores de documentos y nombres
- `packages/validation/engine.py`: motor de validación con reglas para cédulas, extranjeros y duplicados
- `apps/local-agent/watcher.py`: observador local de carpetas para detectar PDFs nuevos
- `apps/api/main.py`: API REST con jobs y resultados persistidos
- `apps/api/database.py`: capa de persistencia con SQLite local por defecto y PostgreSQL compatible
- `apps/web`: dashboard web para cargar PDF, ver expedientes, estados y resultados de procesamiento
- `packages/domain/contracts.py`: contrato tipado para conectar un proveedor OCR sin acoplarlo al flujo PDF
- `packages/ocr/registry.py`: carga opcional de un adaptador OCR mediante `OCR_PROVIDER_FACTORY`
- `tests/test_validation_engine.py`: pruebas de validación y normalización

## OCR y procesamiento PDF

El ingreso conserva el PDF original y calcula su hash y cantidad de páginas. El procesamiento primero intenta leer texto digital embebido. Para PDFs escaneados, se puede conectar un adaptador que implemente `OCRProvider` y devuelva `OCRDocumentText` con texto, número de página y confianza por página. El preview incluye un proveedor local con Tesseract; si no se activa/configura, el expediente se queda en revisión sin afirmar que se extrajeron participantes o documentos.

Para activar un adaptador, configura `OCR_PROVIDER_FACTORY` con el formato `paquete.modulo:nombre_de_fabrica`. Si no hay proveedor configurado, el job queda en `REQUIRES_REVIEW`; el sistema no inventa OCR ni presenta el documento como validado. Incluso con OCR conectado, la extracción estructurada de participantes y documentos y sus reglas aún requieren desarrollo.

Para habilitar OCR local en Windows, instala Tesseract y el modelo de idioma español (`spa.traineddata`), instala las dependencias de `apps/api/requirements.txt` y configura `OCR_PROVIDER_FACTORY=packages.ocr.tesseract_provider:create_tesseract_provider`. El adaptador incluido trabaja localmente sobre el PDF original; no envía páginas a un servicio externo. Ajusta `TESSERACT_CMD`, `TESSERACT_TESSDATA_DIR`, `TESSERACT_LANGUAGES`, `TESSERACT_DPI` y `TESSERACT_PSM` a tu instalación y reinicia la API. En páginas con baja confianza o términos de identidad, se prueban además imágenes en escala de grises con contraste/enfoque mejorados y los modos de segmentación 6 y 11; se conserva la lectura con mejor confianza antes de contar candidatos. Los conteos y candidatos OCR son ayudas de navegación, no validaciones ni prueba de identidad.

### Cotejo asistido de cédulas

En el detalle del expediente, el revisor puede cotejar una fila de la lista con la página del documento original. Debe introducir ambos números, referenciar la fila (por ejemplo `Fila 12`), indicar las dos páginas y revisar visualmente nombre y foto/documento. La API vuelve a validar en servidor que ambos valores tengan 11 dígitos, pasen el dígito de control y coincidan exactamente. Solo devuelve `CORRECTO` cuando además el revisor declara haber confirmado la asociación visual. Un error de formato queda `NO_VERIFICABLE`; un dígito incorrecto, números distintos o asociación visual pendiente queda `REVISIÓN`, nunca rechazo automático.

Los números enviados se comparan en memoria y no se guardan en el resultado, metadatos o auditoría. Se registra la referencia de fila, revisor, páginas, reglas aplicadas y resultado; volver a cotejar la misma fila actualiza su resultado y deja un nuevo evento de auditoría. Si se reprocesa el PDF, los cotejos previos se invalidan y deben repetirse sobre la nueva extracción/evidencia. Los permisos requieren una sesión autenticada y el original debe estar disponible en el almacenamiento gestionado. En producción, usa HTTPS, limita el acceso a personal autorizado y aplica las políticas institucionales de protección y retención de datos. Esta función registra una declaración de revisión humana; no utiliza reconocimiento facial, consulta el padrón oficial ni certifica por sí misma la autenticidad del documento.

## Vista previa web

Inicia la API en `http://127.0.0.1:8000` y sirve `apps/web` en el puerto `3000` para abrir el dashboard en `http://127.0.0.1:3000`. El panel consulta los jobs reales de la API, permite cargar PDF y muestra el resultado y estado de cada expediente. También se puede servir el stack con Docker Compose cuando estén disponibles las imágenes/configuraciones de todos los servicios.

El dashboard permite filtrar/buscar y paginar jobs, abrir el PDF original como evidencia, consultar resultados, cotejar manualmente cédulas y guardar revisión humana, observaciones y estado final opcional. También presenta métricas agregadas de jobs/resultados y un historial de auditoría. Estas decisiones se registran en `validation_results`, `human_reviews` y `audit_events`; no escriben en INICIOS ni otros sistemas institucionales. Jobs sin PDF disponible en el almacenamiento gestionado se excluyen del dashboard y se cuentan como registros sin evidencia disponible. El OCR no extrae todavía una tabla estructurada de participantes ni enlaza automáticamente cada documento con una fila; la asociación y la confirmación visual corresponden al revisor.

La vista previa embebida renderiza una página cada vez a PNG en la API local con PyPDFium2; usa los controles de página para navegar el documento. El endpoint de vista previa requiere sesión y solo sirve evidencia dentro del almacenamiento gestionado. El enlace **Abrir en otra pestaña** conserva acceso al PDF original.

## Base de acciones formativas

La vista **Acciones formativas** muestra el catálogo importado desde el archivo de inicios. Un administrador puede cargar un `.csv` exportado de Drive o un `.xlsx`; para Excel se usa `openpyxl`, incluido en las dependencias. SIVAF busca la fila de encabezados dentro de las primeras 50 filas y reconoce, entre otras variantes, las columnas de código, acción formativa, fecha de inicio y estado. El código de acción identifica el registro: las cargas posteriores actualizan coincidencias y agregan códigos nuevos, sin borrar acciones que no aparezcan en una exportación. Cada importación registra usuario, fecha, hash y cantidades insertadas/actualizadas. Se rechazan códigos duplicados o vacíos, archivos no soportados y cargas mayores de 20 MB.

Las cuentas analistas pueden consultar y buscar el catálogo; únicamente cuentas con rol `admin` pueden importarlo o modificarlo desde SIVAF. Este permiso se aplica a través de la aplicación/API, no a quien tenga acceso directo al archivo de base de datos o a la máquina que ejecuta el servidor.

El modo local guarda datos en `infotep.db`. Para que varios puestos NComputing vean y usen los mismos registros, el servidor de SIVAF y una base PostgreSQL compartida deben ejecutarse en un equipo/servidor accesible por la red institucional; no se debe sincronizar el archivo SQLite `infotep.db` mediante Drive mientras está en uso. La actualización diaria puede hacerse cargando la nueva exportación desde la cuenta administradora; los cambios quedan guardados en la base configurada por `DATABASE_URL`.

## Acceso y usuarios

El API y el dashboard requieren iniciar sesión. Las cuentas y sesiones se guardan en la base configurada por `DATABASE_URL`: SQLite (`./infotep.db`) por defecto para desarrollo local, o PostgreSQL para uso compartido. Las contraseñas se guardan con PBKDF2-HMAC-SHA256; el navegador recibe una cookie de sesión `HttpOnly` con vencimiento de ocho horas. No hay cuentas ni contraseñas predeterminadas. Estas son cuentas locales de SIVAF; el inicio de sesión aún no está integrado con Active Directory ni con el proveedor institucional de identidad.

Desde la raíz del proyecto, crea el primer usuario con:

```powershell
.\.venv\Scripts\python.exe -m apps.api.create_user
```

El comando solicita nombre de usuario, rol (`admin` o `analyst`) y contraseña, sin mostrar la contraseña en pantalla. Se requieren al menos 12 caracteres. Para usar PostgreSQL, define primero `DATABASE_URL` con la cadena de conexión del servidor y crea la cuenta contra esa base. En producción, sirve el sitio por HTTPS y configura `SIVAF_COOKIE_SECURE=true`; coordina con Informática la identidad institucional, los roles, las copias de seguridad y la política de acceso antes de habilitarlo en NComputing.

Para el PostgreSQL de Docker Compose, copia `.env.example` a `.env` y reemplaza `POSTGRES_PASSWORD` por una contraseña larga y aleatoria antes de iniciar los servicios. Compose no usa una contraseña débil por defecto; no publiques ni compartas `.env`. La conexión PostgreSQL se construye con los parámetros del entorno y codifica correctamente contraseñas con caracteres reservados.

## Seguridad de red y expedientes

El endpoint heredado `POST /api/v1/jobs`, que aceptaba rutas del sistema de archivos, está deshabilitado (`410 Gone`); los expedientes se crean exclusivamente mediante carga y almacenamiento gestionado en `/api/v1/jobs/upload`. Cada PDF tiene un límite de 50 MiB, 300 páginas y un máximo de píxeles por página al rasterizar; los metadatos de carga se limitan a 16 KiB. El API no devuelve rutas internas del servidor.

Los analistas solo pueden listar, procesar, revisar, ver o descargar sus propios expedientes; administración puede acceder a todos. Las consultas por ID ajeno responden como no encontrado. Las solicitudes de descarga y las vistas previas generadas se agregan al historial de auditoría.

El Compose publica por defecto solo el sitio y el puerto local de desarrollo del API en `127.0.0.1`; PostgreSQL y Redis no se publican (Redis se retiró porque la API no lo usa). Nginx sirve los estáticos y pasa `/api/` y `/health` al servicio API por la red interna, con CSP y encabezados de seguridad. Para acceso desde Registro/NComputing, instala un proxy TLS institucional delante del puerto local `3000`, restringe por firewall la interfaz de administración y conserva `SIVAF_COOKIE_SECURE=true`. No publiques directamente los puertos de PostgreSQL, API o el HTTP interno de Nginx en la LAN/Internet. Confirma certificados, HSTS, firewall y DNS con Informática: el TLS público depende de ese proxy y no se puede dar por activo solo con el Compose.

Para desarrollo local sin HTTPS, `SIVAF_COOKIE_SECURE=false` puede usarse únicamente en una máquina de confianza y no debe llevarse a producción. El modo de desarrollo que sirve la carpeta web directamente puede conectarse al API de loopback; en Docker Compose, el proxy web permite las llamadas por la misma ruta `/api/`.

## Recomendaciones para el dashboard

- Prioriza una bandeja de trabajo con filtros por estado, fecha, código de acción y responsable, además de búsqueda y exportación autorizada.
- Distingue claramente estados técnicos (recibido, procesado, OCR pendiente/error) de decisiones humanas; el procesamiento final no equivale a aprobación.
- Añade paginación en el servidor, indicadores de antigüedad/SLA y acciones masivas solo después de definir permisos y trazabilidad.
- Antes de producción, confirma con Registro e Informática qué datos se pueden mostrar, quién puede ver/descargar los PDF, cuánto tiempo conservarlos y cómo auditar accesos.
- OCR, extracción de participantes y validación contra datos fuente siguen pendientes; no presentes sus resultados como disponibles hasta conectar y probar un proveedor y muestras representativas.

## Objetivo

Automatizar la verificación documental de una acción formativa, conservando el PDF original como evidencia y dejando la decisión final en manos del usuario, sin modificar sistemas institucionales externos.

## Arquitectura propuesta

- Backend: Python + FastAPI
- Frontend: React + TypeScript
- Base de datos: PostgreSQL
- Workers: Python async workers
- OCR: capa abstracta con proveedores intercambiables
- Storage: abstracción para almacenamiento local y S3-compatible
- Local Agent: componente separado para vigilar la carpeta del escáner
- Infraestructura: Docker + Docker Compose

## Estructura de carpetas

- apps/api: API principal
- apps/web: frontend web
- apps/worker: workers de procesamiento
- apps/local-agent: agente local del escáner
- packages/domain: entidades y lógica del negocio
- packages/validation: motor de reglas y validación
- packages/ocr: proveedores OCR
- packages/document-processing: extracción y estructura de PDF
- packages/shared: utilidades compartidas
- infrastructure/database: migraciones y esquema
- infrastructure/storage: almacenamiento
- infrastructure/docker: configuración de contenedores
- docs: documentación técnica
- tests: pruebas unitarias, de integración y de fixtures

## Principios clave

- No inventar datos
- No modificar sistemas institucionales automáticamente
- Mantener evidencia original del PDF
- Separar extracción, normalización y validación
- Registrar auditoría y trazabilidad
- Mantener reglas evaluables y reproducibles
- Dejar decisiones ambiguas para revisión humana

## Siguientes pasos

1. Confirmar la estructura propuesta
2. Definir modelos y contratos base
3. Preparar el scaffold inicial de backend/frontend/worker
4. Diseñar el motor de reglas y validación
5. Revisar el PDF real para ajustar estructura y OCR

## Documentación adicional

- [docs/architecture.md](./docs/architecture.md)
