# Sprint 10: auditoría de dependencias y acciones

Fecha de implementación: 26 de octubre de 2026. Sprint 10 visible en Jira:
16–25 de octubre, todavía abierto en el tablero. Alcance asignado a Yehosua:
SCRUM-710 y SCRUM-747–751. Base: `ed8138b`, que ya incluye el PR #41 de pruebas.

## SCRUM-710: auditoría de dependencias en CI

`.github/workflows/dependency-audit.yml` ejecuta pip-audit 2.10.1 con Python 3.11
para `requirements.txt` y `requirements-dev.txt`, incluyendo las dependencias
transitivas resueltas. Se dispara en pull requests, push a main y ejecución manual.
Cada job tiene permisos de lectura, timeout de 10 minutos y conserva JSON por
14 días incluso si la auditoría falla. No usa credenciales ni base de datos.

El comando usa `--strict`, sin exclusiones ni `continue-on-error`: vulnerabilidades
o errores de resolución impiden aprobar el job. El workflow de despliegue no se
modifica. Para que esta verificación bloquee obligatoriamente un merge, el
mantenedor debe marcar ambos checks como requeridos en las reglas de la rama;
este PR no modifica permisos ni reglas de GitHub.

### Resultado local y pendientes

Se ejecutaron los mismos comandos con Python 3.11 en un contenedor oficial.
Ambos targets respondieron exit code **1**: 15 entradas de vulnerabilidad,
correspondientes a **8 pares únicos paquete/advisory en 3 paquetes**. Hay IDs
repetidos en la respuesta del proveedor; no son 15 defectos distintos del código.
Se conservan las respuestas sin suprimir hallazgos:

- `dependency-audit.json`: dependencias de ejecución.
- `dependency-audit-dev.json`: ejecución más desarrollo.

| Paquete resuelto | Versión | Tratamiento pendiente |
|---|---|---|
| python-jose | 3.5.0 | El reporte no ofrece versión corregida; evaluar aplicabilidad al uso HS256 y alternativa con pruebas de compatibilidad |
| ecdsa | 0.19.2 | Dependencia transitiva de python-jose sin versión corregida indicada; evaluar sustitución/aplicabilidad |
| starlette | 0.48.0 | El reporte indica versiones corregidas posteriores; coordinar actualización compatible de FastAPI/Starlette y verificar contratos |

**El CI de auditoría debe quedar rojo con estas dependencias.** La incorporación
del auditor está implementada; no se afirma que los paquetes estén libres de
vulnerabilidades ni que el sistema esté listo para desplegar. No se cambian a
ciegas las dependencias de autenticación/framework dentro de una tarea de CI.
Las correcciones de dependencias corresponden al trabajo de la historia SCRUM-683
y deben acordarse con sus responsables. No se ha aceptado ningún riesgo ni se
propone una exclusión automática para conseguir verde.

Reproducir en Python 3.11 desde la raíz:

```bash
python -m pip install pip-audit==2.10.1
python -m pip_audit -r requirements.txt --strict --format=json --output=dependency-audit.json
python -m pip_audit -r requirements-dev.txt --strict --format=json --output=dependency-audit-dev.json
```

La resolución es del 26 de octubre, no un lockfile reproducible con hashes.
Nuevos advisories o dependencias transitivas pueden cambiar el resultado.
Fuente del auditor: [PyPA pip-audit](https://github.com/pypa/pip-audit).

## SCRUM-747: mecanismos existentes

El historial `reporte` conserva quién generó reportes y la fecha. Los movimientos
registran usuario/producto/stock y las ventas su autor. El logger del servidor
sirve para diagnóstico. Ninguno ofrecía un historial consultable común de
cambios críticos. Las pruebas anteriores de auditoría verificaban solo reportes;
se conservan y complementan, sin atribuirles cobertura de la nueva tabla.

## SCRUM-748 y 750: eventos y transacciones

| Evento | Operación cubierta | Entidad registrada |
|---|---|---|
| movement.created | Movimiento manual y ajustes que pasan por `create_inventory_movement` | ID del movimiento |
| sale.created | Venta y cambios de stock de sus líneas, como una sola operación | ID de venta |
| product.status_changed | Activar/desactivar producto | ID de producto |
| supplier.status_changed | Activar/desactivar o soft delete de proveedor | ID de proveedor |
| client.status_changed | Activar/desactivar cliente | ID de cliente |
| client.deactivated | Soft delete de cliente | ID de cliente |
| user.updated | Actualización de username | ID de usuario afectado |
| user.role_changed | Actualización que incluye role_id | ID de usuario afectado |
| user.status_changed | Activar/desactivar usuario | ID de usuario afectado |
| user.deactivated | Soft delete de usuario | ID de usuario afectado |
| tax_configuration.updated | Actualización de tasa tributaria | ID de configuración |

Se registran solo operaciones exitosas de esta lista. La escritura del evento se
hace **antes del commit, en la misma sesión/transacción** que la modificación.
No hay commit independiente del logger ni cola en memoria. Si no se puede escribir
el evento, se revierte el cambio; un fallo de negocio no deja un evento de éxito.
Una venta no genera una segunda auditoría por cada movimiento interno.

Campos: UUID del evento, fecha UTC, UUID del actor, acción, tipo de entidad e ID
modificado. No se reciben cuerpos completos, contraseñas, tokens, correos,
nombres ni metadata arbitraria. El evento identifica la acción; no es un diff de
los valores anteriores/posteriores. Intentos fallidos, login, reset de contraseña,
altas de usuarios/productos, importaciones y otras escrituras fiscales no se
presentan como auditadas por este primer catálogo.

## SCRUM-749: almacenamiento y migración

Nueva tabla `audit_event` en cada esquema tenant, incorporada al registro de
modelos y al bootstrap existente. `init_db` la crea para empresas existentes al
arranque; el registro de nuevas empresas también usa ese bootstrap. No se
reconstruye historial anterior al despliegue. Los actores se guardan por UUID
sin borrado en cascada de eventos.

El índice `(occurred_at, id)` permite páginas ordenadas. El bootstrap ahora crea
explícitamente índices faltantes en tablas existentes: `create_all` por sí solo
no los añade cuando la tabla ya existe. Se verificó dos veces sobre el mismo
esquema PostgreSQL y se conservó el conteo de movimientos.

Los índices se crean de forma normal, no `CONCURRENTLY`: planificar ventana de
mantenimiento para tenants grandes y ejecutar bootstrap una sola vez antes de
levantar varias réplicas. No se añade `ALTER/DROP` destructivo para esta función.

La aplicación no tiene endpoints para editar o borrar eventos. **No es un log
inmutable frente al administrador de PostgreSQL**: usa la cuenta de la aplicación.
Quedan pendientes permisos DB dedicados/almacenamiento externo resistente a
alteración, política de retención y monitoreo de crecimiento según requisitos del
equipo. No se habilita retención automática que borre evidencia.

## SCRUM-751: consulta protegida

```text
GET /api/v1/audit/events?limit=50&cursor=...&action=movement.created&actor_id=<uuid>
```

Respuesta `{items, next_cursor}`; límite 1–100 y cursor con longitud máxima 1024.
Requiere admin o superior según la jerarquía existente **y una empresa activa**.
Un superadmin sin empresa no obtiene un listado global. No se permite elegir un
esquema/empresa por query: se resuelve desde el usuario autenticado.

Paginación keyset descendente por `(occurred_at, id)`. El cursor incluye el
contexto de empresa y filtros, no un nombre de esquema; cambiar el contexto da
422 genérico. No es una credencial ni una firma: la autorización siempre viene
del token y la consulta limitada al esquema propio.

## Validación y límites

Pruebas nuevas de persistencia tras reconexión, rollback, fallo al insertar
auditoría, permisos, aislamiento, filtros y paginación estable. Las fixtures de
pruebas previas incorporan la tabla y la identidad del actor; no se desactiva ni
mockea la escritura de auditoría para conseguir resultados verdes.

La verificación HTTP/PostgreSQL real está en
`docs/performance/sprint10/postgres-verification.json` y se reproduce con
`scripts/verify_sprint10.py`, únicamente con el fixture sintético y base local
creados por `tests/load/seed_load_data.py`. Se comprobaron 14 condiciones.

La validación externa después de desplegar, las reglas requeridas de la rama,
la remediación de dependencias y la política de conservación del registro siguen
pendientes. No se modifican estados ni se cierran tickets Jira automáticamente.


Resultado final local: **3319 pruebas aprobadas, 5 omitidas y 5 subtests
aprobados**, en 31.24 segundos. Las omitidas requieren integración PostgreSQL
específica del chat o llamadas reales a Z.AI; la verificación PostgreSQL del
Sprint 10 se ejecutó por separado y aprobó 14 condiciones. Los 21 casos del
archivo nuevo de auditoría/paginación también aprobaron.
