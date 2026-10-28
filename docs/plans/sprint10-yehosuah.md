# Sprint 10 — trabajo de Yehosua

Tablero revisado el 26/10/2026. Sprint 10: 16–25/10, todavía abierto en Jira.
Rama: `yehosuah/sprint10-audit-performance`, desde `origin/main` en `ed8138b`.
El PR anterior #38 ya estaba integrado. No se modifican estados Jira ni se despliega.

## Resultado buscado

Administradores pueden consultar acciones críticas reales de su empresa; cambios
y eventos se confirman o revierten juntos. Consultas grandes de movimientos tienen
una alternativa paginada compatible. El CI detecta y conserva evidencia de
vulnerabilidades de dependencias. Las conclusiones de rendimiento distinguen
implementación, carga medida y pendientes de producción.

## Alcance asignado y evidencia

| Ticket | Trabajo realizado | Evidencia / límite |
|---|---|---|
| SCRUM-710 | Auditoría runtime/dev en CI con artefactos aun al fallar | Workflow y JSON en `docs/security/sprint10`; falla por vulnerabilidades previas, no se suprimen |
| SCRUM-747 | Revisión de reportes, movimientos y logger existentes | Documento de auditoría; no existía un registro general |
| SCRUM-748 | Catálogo explícito de eventos críticos y datos mínimos | Tabla de eventos en documento de seguridad |
| SCRUM-749 | Modelo audit_event por tenant y bootstrap idempotente | Migración PostgreSQL repetida preserva datos e índices |
| SCRUM-750 | Eventos en la transacción de operaciones críticas | Pruebas de persistencia y rollback, incluido fallo al registrar auditoría |
| SCRUM-751 | GET /audit/events protegido y limitado por empresa | Matriz de permisos, tests negativos y HTTP/PG real |
| SCRUM-793 | Revisión del escenario existente y nueva línea base | No había raw histórico versionado; `before.json` |
| SCRUM-794 | Identificación de endpoints de mayor p95 | Movimientos completos primero; tabla por endpoint en resúmenes |
| SCRUM-795 | Revisión del listado sin límite y contrato consumido | Se preserva `/movements` para compatibilidad |
| SCRUM-796 | Ruta `/movements/page`, keyset e índices | Casos de fechas iguales, inserciones, filtros y tenant distinto |
| SCRUM-797 | Presupuesto de conexiones por proceso revisado | Documentados defaults y multiplicación por workers; no se amplía sin evidencia |
| SCRUM-798 | Evaluación local de uno/dos workers | Se conserva un worker por límites en memoria y arranque de migración |
| SCRUM-799 | Carga real k6 con PG descartable | 25/50/100 VUs, cuatro corridas secuenciales |
| SCRUM-800 | Comparación p95, errores y payload | Se conserva también el empeoramiento de la ruta legacy y el umbral original |
| SCRUM-801 | Optimizaciones y reproducción documentadas | `docs/performance/sprint10/README.md` |

## Criterio de cierre

Implementación local y PR para revisión no equivalen a despliegue certificado.
Siguen pendientes remediar dependencias, adoptar cursor desde frontend,
coordinar límites compartidos si se desea multi-worker, definir conservación y
protección DB del log y validar el entorno real. No se acepta riesgo por defecto.

Las horas de esta sesión no se presentan como tiempo manual efectivo del usuario.
El LOGT puede completarse con las actividades verificadas y los tiempos reales.
