# Revisión de seguridad del backend

Control de calidad sobre autenticación, autorización y aislamiento de información
entre empresas. Revisión hecha sobre `main` en `efb82ae`, septiembre de 2026.

## Alcance

- Las 55 rutas que registra la aplicación, públicas y protegidas.
- Autenticación: tokens de acceso, tokens de invitación y de recuperación.
- Autorización por rol, positiva y negativa.
- Aislamiento entre empresas, tanto en los esquemas `tenant_*` como en las tablas
  globales (`users`, `companies`).
- Analítica de inventario (`/inventory/analytics/*`, `/metrics`, `/history`) y los
  reportes que reutilizan su rango de fechas.
- Manejo de errores: qué ve el cliente cuando algo falla.

Fuera de alcance: los módulos `/api/v1/analytics` y `/api/v1/ai` que todavía no
están en `main` (ver F12), infraestructura y dependencias.

## Método

1. Inventario de rutas. `ROUTE_POLICY` en `tests/security_helpers.py` clasifica
   cada ruta como pública, autenticada, propia, manager, admin o superadmin
   estricto, y `tests/test_security_route_inventory.py` la compara contra las rutas
   reales de la aplicación.
2. Pruebas automatizadas que recorren esa tabla ruta por ruta y rol por rol, con la
   aplicación real y una base simulada que registra cada consulta.
3. Reproducción manual de cada hallazgo antes de corregirlo, y la misma
   reproducción después de la corrección.
4. Validación final contra un PostgreSQL local con dos empresas reales (ver
   "Validación final").

## Severidad

| Nivel | Criterio |
|---|---|
| Alta | Permite acceder a datos o acciones sin la credencial o el rol correctos, o rompe una operación normal |
| Media | Expone información interna o de otra empresa, o convierte un error del cliente en un 500 |
| Baja | Inconsistencia o endurecimiento sin impacto directo |

## Resumen

25 hallazgos: 3 altos, 12 medios y 10 bajos. 16 corregidos en esta revisión, 8
documentados como recomendación y 1 en seguimiento hasta que se integre el módulo
nuevo de analítica.

Estados: **Verificado** es corregido y comprobado contra PostgreSQL real en la
validación final. **Corregido** es corregido y cubierto por pruebas automatizadas,
pero no se puede reproducir en vivo sin inyectar una falla (una excepción inesperada,
la base caída o el SMTP caído).

| Id | Sev. | Área | Hallazgo | Estado |
|---|---|---|---|---|
| F01 | Alta | Autenticación | Los tokens de invitación y de recuperación servían como token de acceso | Verificado |
| F02 | Alta | Autenticación | Una invitación vieja reactivaba una cuenta desactivada y reemplazaba su contraseña | Verificado |
| F03 | Alta | Errores | Un error de validación con límites decimales o validadores propios respondía 500 | Verificado |
| F04 | Media | Errores | Siete endpoints de inventario devolvían el texto del error de base de datos | Corregido |
| F05 | Media | Errores | Las respuestas 422 repetían el cuerpo enviado, contraseñas incluidas | Verificado |
| F06 | Media | Aislamiento | Reenviar invitación revelaba si un usuario de otra empresa existía y si estaba activo | Verificado |
| F07 | Media | Aislamiento | Crear un empleado con un correo de otra empresa respondía 500 | Verificado |
| F08 | Media | Errores | Renombrar un usuario con un username ocupado respondía 500 | Verificado |
| F09 | Media | Analítica | Fechas cercanas al año 1 desbordaban el cálculo del rango y respondían 500 | Verificado |
| F10 | Media | Aislamiento | Usuarios de una empresa inactiva podían iniciar sesión y usar las rutas globales | Verificado |
| F11 | Media | Aislamiento | Un id de usuario de otra empresa respondía 403 y uno inexistente 404 | Verificado |
| F12 | Media | Analítica | Las rutas nuevas de `/api/v1/analytics` y `/api/v1/ai` solo exigen sesión | Seguimiento |
| F13 | Baja | Autenticación | Un token sin `sub` válido respondía 500 | Verificado |
| F14 | Baja | Errores | Las excepciones no controladas respondían texto plano fuera del contrato JSON | Corregido |
| F15 | Baja | Autorización | Un admin podía desactivar su propia cuenta con `PATCH /users/{id}/status` | Verificado |
| F16 | Baja | Errores | `/ready` respondía 500 con la base caída | Corregido |
| F17 | Baja | Errores | Los fallos de correo se imprimían por consola con la dirección del destinatario | Corregido |
| F18 | Media | Autenticación | `/auth/login` no limita intentos fallidos | Recomendación |
| F19 | Media | Autenticación | No hay largo mínimo de contraseña | Recomendación |
| F20 | Media | Disponibilidad | La importación xlsx limita el archivo, no su tamaño descomprimido | Recomendación |
| F21 | Baja | Exposición | `/docs` y `/openapi.json` son públicos en producción | Recomendación |
| F22 | Baja | Autorización | `employee` lee los movimientos crudos que la analítica reserva a `manager` | Recomendación |
| F23 | Baja | Configuración | `SECRET_KEY` no se valida al arrancar | Recomendación |
| F24 | Baja | Autenticación | El login responde más rápido para correos inexistentes | Recomendación |
| F25 | Baja | Autenticación | Un token de recuperación sigue siendo válido 48 h después de usarse | Recomendación |

## Hallazgos corregidos

### F01. Tokens de invitación y recuperación aceptados como sesión

**Qué pasaba.** Los enlaces de invitación y de recuperación llevan un JWT firmado
con la misma clave que los tokens de acceso, con `purpose` y 48 h de vida.
`get_current_user` no miraba `purpose`, así que ese token abría una sesión de 48 h
en cualquier endpoint protegido.

**Reproducción.** `GET /api/v1/users` con `Authorization: Bearer <token de
recuperación de un admin>` respondía 200 con el listado de usuarios.

**Corrección.** `get_current_user` rechaza con 401 cualquier token que traiga
`purpose`.

**Prueba.** `test_security_authentication.py`, casos `set password token` y `reset
password token` sobre las 48 rutas protegidas.

### F02. Invitación reutilizable

**Qué pasaba.** `/auth/password/set` no revisaba el estado del usuario. Con una
invitación vigente se podía volver a fijar la contraseña de una cuenta activa, o
reactivar una cuenta que un admin había desactivado.

**Corrección.** Los usuarios pendientes se crean con contraseña vacía. Si el
usuario ya tiene contraseña, la invitación se considera usada y responde 400
`Invitation already used`. La contraseña se reclama con un `UPDATE` condicional
(`WHERE password = ''`), así que dos solicitudes simultáneas con el mismo enlace no
pueden pasar las dos: con 10 solicitudes a la vez contra PostgreSQL, antes
respondían 200 todas, ahora responde 200 solo una.

**Efecto a tener en cuenta.** Reenviar una invitación a una cuenta desactivada
envía un enlace que ahora se rechaza. Para reactivar una cuenta se usa
`PATCH /users/{id}/status`.

**Prueba.** `test_security_negative_authorization.py`, sección de invitaciones.

### F03 y F05. Respuestas de validación

**Qué pasaba.** El manejador de 422 devolvía `exc.errors()` tal cual. Ese detalle
incluye `input`, el valor enviado, que en un campo faltante es el cuerpo completo
con la contraseña, y `ctx`, que puede traer un `Decimal` o el propio `ValueError`.
Esos dos tipos no se serializan a JSON, así que un precio negativo, una cantidad en
cero o una actualización de tarea vacía terminaban en un 500 de texto plano.

**Corrección.** Cada error se reduce a `loc`, `msg` y `type`.

**Prueba.** `test_security_error_handling.py`, `test_invalid_input_is_a_clean_422` y
`test_a_validation_error_does_not_echo_the_password`.

### F04. Errores de base de datos en la respuesta

**Qué pasaba.** Actualizar proveedor, su estado, el estado de producto, registrar un
movimiento y las tres operaciones de proveedor por producto respondían
`AppError(500, f"... {str(e)}")`. El texto de un error de SQLAlchemy incluye la
sentencia, el esquema `tenant_*` y los parámetros.

**Corrección.** Mensaje genérico para el cliente y `logger.exception` para el
servidor, igual que ya hacía la generación de reportes.

**Prueba.** `test_a_database_failure_does_not_reach_the_client` y una prueba que
recorre `app/` con `ast` y falla si algún `AppError` vuelve a formatear la
excepción capturada.

### F06, F07 y F11. Identificadores de otra empresa en tablas globales

**Qué pasaba.** Usuarios y empresas comparten tabla, así que el filtro por empresa
lo hacen los services.

- `PUT`, `PATCH` y `DELETE /users/{id}` respondían 403 para un usuario de otra
  empresa y 404 para uno inexistente: la diferencia confirmaba que el id existía.
- Reenviar invitación revisaba el estado antes que la empresa, y respondía 400
  "already active" para un usuario activo de otra empresa.
- Crear un empleado solo buscaba el correo dentro de la empresa del admin. Como el
  correo es único en toda la tabla, el insert chocaba con el índice y respondía 500.

**Corrección.** Un usuario de otra empresa responde exactamente igual que uno
inexistente: 404 `User not found`. La invitación revisa la empresa primero. El
correo se busca en todas las empresas y responde 400 `Email already registered`.

El superadmin conserva su 403 `Cannot modify a superadmin user`: no pertenece a
ninguna empresa y no hay otro tenant que ocultar.

**Prueba.** `test_security_cross_tenant.py`.

### F08. Username repetido al actualizar

Se valida antes de escribir y responde 400 `Username already registered`.

### F09. Rango de analítica fuera del calendario

`?period=7d&end_date=0001-01-02` restaba el período a la fecha final y desbordaba.
Ahora responde 400. La corrección está en `_resolve_analytics_range`, que también
usan los reportes de movimientos y alertas.

### F10. Empresa inactiva

Las rutas de tenant ya la rechazaban al resolver el esquema, pero las globales
(usuarios, empleados, roles) no. Ahora `get_current_user` responde 403 `Company is
inactive` en todas las rutas, y el login también, siempre después de validar la
contraseña para no revelar qué correos existen.

### F13 a F17

- F13: un token sin `sub`, o con un `sub` que no es UUID, responde 401 sin llegar a
  la base. Lo mismo en `/password/set` y `/password/reset`, con 400.
- F14: un manejador para `Exception` responde `{"message": "Internal server
  error", "code": "internal_error", "errors": []}`. Starlette vuelve a lanzar la
  excepción después, así que el servidor sigue registrando el traceback.
- F15: `PATCH /users/{id}/status` sobre la propia cuenta responde 400, como ya hacía
  `DELETE`.
- F16: `/ready` responde 503 `Database is not ready`.
- F17: los fallos de correo van al logger con el id del usuario y la clase de la
  excepción, no la dirección.

## Cambios visibles para el frontend

| Situación | Antes | Ahora |
|---|---|---|
| Error de validación | 422 con `input` y `ctx`, o 500 | 422 con `loc`, `msg` y `type` por error |
| Usuario de otra empresa en `/users/{id}` | 403 `Not authorized` | 404 `User not found` |
| Reenviar invitación a usuario de otra empresa | 400 o 403 | 404 `User not found` |
| Invitación ya usada | 200 | 400 `Invitation already used` |
| Usuario de empresa inactiva | Entraba a rutas globales | 403 `Company is inactive`, también en login |
| Correo o username ocupados | 500 | 400 |
| Error no controlado | Texto plano | JSON con `code: internal_error` |

## Seguimiento: F12

Los PRs #31 y #32 agregan `/api/v1/analytics/*` (métricas y tendencia de ventas,
riesgo de inventario, productos más vendidos, tendencia de creación de productos) y
`POST /api/v1/ai/analysis`. Resuelven el esquema con `get_user_schema_name`, así
que el aislamiento entre empresas está bien, pero todas usan `get_current_user`:
cualquier `employee` ve las métricas de ventas y puede disparar el análisis, que
envía agregados de la empresa a un proveedor externo con costo por llamada.

Recomendación: `require_role("manager")` en las dos, igual que la analítica de
inventario, y un límite de solicitudes por empresa en `/ai/analysis`. Cuando se
integren, `test_security_route_inventory.py` va a fallar hasta que las rutas se
clasifiquen en `ROUTE_POLICY`: es el aviso buscado.

## Recomendaciones

- **F18.** Limitar intentos de login por correo y por IP. El límite de
  `/password/forgot` vive en memoria del proceso; para login conviene uno compartido
  entre contenedores.
- **F19.** Exigir un largo mínimo, por ejemplo 8 caracteres, en `new_password` de
  `/password/set` y `/password/reset`.
- **F20.** Revisar `ZipInfo.file_size` de `xl/worksheets/sheet1.xml` y
  `sharedStrings.xml` antes de leerlos: un xlsx de 5 MB puede descomprimir a varios
  GB.
- **F21.** Desactivar `/docs`, `/redoc` y `/openapi.json` en producción, o dejarlos
  detrás de autenticación.
- **F22.** Decidir si `employee` debe leer `/inventory/movements`. Hoy la matriz lo
  permite a propósito, pero con esos datos se reconstruye la analítica que exige
  `manager`.
- **F23.** Fallar al arrancar si `SECRET_KEY` falta o es corta.
- **F24.** Verificar contra un hash fijo cuando el correo no existe, para igualar el
  tiempo de respuesta.
- **F25.** Incluir en el token de recuperación una huella de la contraseña actual,
  para que deje de servir apenas se usa.

## Cómo correr las pruebas de seguridad

```bash
.venv/bin/python -m pytest tests/test_security_*.py -q
```

| Archivo | Qué cubre | Pruebas |
|---|---|---|
| `test_security_route_inventory.py` | Toda ruta clasificada y su guard alineado | 113 |
| `test_security_authentication.py` | Credenciales inválidas en cada ruta protegida | 636 |
| `test_security_roles.py` | Cada rol permitido pasa el guard | 142 |
| `test_security_negative_authorization.py` | Roles insuficientes y escalamiento | 104 |
| `test_security_tenant_isolation.py` | Cada consulta nombra solo el esquema propio | 169 |
| `test_security_cross_tenant.py` | Ids de otra empresa en rutas, cuerpos y filtros | 34 |
| `test_security_analytics.py` | Agregados sin datos ajenos, fechas inválidas | 39 |
| `test_security_error_handling.py` | Errores sin detalles internos | 22 |

## Validación final

**Suite completa.** 1915 pruebas en verde, contra 656 en `main`: 1259 nuevas de
seguridad. Corre en unos 13 segundos, porque la semilla de pruebas ahora calcula el
hash bcrypt una sola vez por sesión en lugar de cinco veces por prueba.

**Ejecución en vivo.** Un PostgreSQL 16 descartable en un puerto propio, dos copias
del código (`main` en `efb82ae` y esta rama) y el mismo guion HTTP contra ambas. El
superadmin registra dos empresas; cada una recibe un admin, un manager y un
employee que activan su cuenta con la invitación, y datos propios: proveedor,
producto, movimiento, cliente, venta y tarea. Los correos se capturaron en un
archivo local, no se envió ninguno, y no se usó la base configurada en `.env`.

| Grupo | Comprobaciones | `main` | Esta rama |
|---|---|---|---|
| Rutas protegidas sin token, token vencido y firma ajena | 3 | 3 | 3 |
| Roles permitidos, roles negados y escalamiento | 11 | 11 | 11 |
| Listados de usuarios, productos y clientes por empresa | 3 | 3 | 3 |
| Ids de otra empresa en rutas, cuerpos, filtros y reportes | 25 | 25 | 25 |
| Analítica: cada empresa solo suma lo suyo | 4 | 4 | 4 |
| Reproducción de F01, F02, F03, F05 a F11, F13, F15 y F16 | 25 | 3 | 25 |
| Preparación | 1 | 1 | 1 |
| **Total** | **72** | **50** | **72** |

La primera comprobación de la tabla recorre en una sola pasada las 48 rutas
protegidas.

Las 22 fallas de `main` son exactamente los hallazgos: ninguna comprobación falla por
otro motivo, y el aislamiento entre empresas en las tablas `tenant_*` ya se sostenía
antes de esta revisión. El log del servidor de `main` registró 8 excepciones no
controladas durante la ejecución; el de esta rama, ninguna.

Dos hallazgos solo se ven completos contra PostgreSQL real, porque la base simulada
de las pruebas no los reproduce:

- F13: un `sub` que no es UUID llega a la base, que falla al convertirlo y responde
  500.
- F07: el índice único de `users.email` rechaza el insert y responde 500.
