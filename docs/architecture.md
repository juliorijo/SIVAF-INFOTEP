# Arquitectura del sistema

## Objetivo

Diseñar una solución modular para la verificación documental de acciones formativas, con automatización del flujo de procesamiento, evidencia conservada, validación por reglas y revisión humana.

## Principios arquitectónicos

- Separar extracción de datos, normalización y validación
- Mantener el PDF original completo como evidencia
- Un solo punto de verdad para reglas y auditoría
- Componentes desacoplados para OCR, storage y workers
- Reproducibilidad del procesamiento
- Trazabilidad de decisiones humanas

## Capas

### 1. Dominio

Contiene las entidades principales del negocio y los contratos de servicios. No depende de frameworks externos.

Entidades clave:
- User
- Role
- Permission
- FormativeAction
- Participant
- IdentityDocument
- ProcessingJob
- ValidationRule
- ValidationResult
- Incident
- Review
- AuditLog

### 2. Aplicación

Orquesta los casos de uso del negocio. Implementa servicios del tipo:
- PdfIngestionService
- FormativeActionIdentificationService
- ParticipantExtractionService
- DocumentExtractionService
- IdentityNormalizationService
- DocumentAssociationService
- ValidationService
- EvidenceService

### 3. Infraestructura

Abstrae dependencias técnicas:
- PostgreSQL repositories
- OCR provider implementations
- Local storage / S3-compatible storage
- Worker queue and task orchestration
- Watcher for scanner directory

### 4. Interfaces

- API REST con FastAPI
- Web frontend con React + TypeScript
- Local Agent para detección automática de PDFs

## Flujo principal

1. El Local Agent detecta un PDF en la carpeta de ingreso.
2. Se crea un ProcessingJob y se guarda el archivo original.
3. El worker procesa el PDF como unidad reproducible.
4. Se identifica la acción formativa.
5. Se extraen participantes y documentos.
6. Se normalizan números y nombres.
7. Se asocian documentos a participantes por número normalizado.
8. Se ejecuta el motor de reglas.
9. Se genera evidencia y resultados con motivo estructurado.
10. El usuario revisa resultados, decide y registra auditoría.

## Motor de reglas

El motor de reglas debe:
- evaluar reglas por código
- devolver estado: CORRECTO, REVISIÓN, INCIDENCIA, NO_VERIFICABLE
- mantener un motivo estructurado
- guardar evidencia vinculada al resultado
- permitir extensibilidad por versión

## Recomendación de implementación

- La lógica del negocio debe vivir en packages/domain y packages/validation
- La API solo debe orquestar casos de uso
- El frontend debe consumir información ya normalizada
- El worker debe encargarse de tareas pesadas de extracción y validación
- El OCR debe estar aislado detrás de interfaces claras

## Riesgos clave

- PDF real con estructura no conocida
- OCR inestable con nombres y cédulas
- Ambigüedad entre revisión e incidencia
- Asociación incorrecta de documento a participante
- Pérdida de trazabilidad si no se guarda evidencia original

## Siguiente fase

Se debe validar la estructura real del PDF de ejemplo antes de fijar columnas o reglas concretas. Esto evitará implementar lógica falsa basada en supuestos.
