# Flowdesk Backend

El Chatbot del Sprint 8 está documentado en
[el contrato de chat](docs/ai-chat-contract.md) y
[el plan acordado](docs/plans/sprint8-ai-chat.md). Incluye herramientas de consulta,
chat e historial privado para managers/admins, con caducidad de 15 días desde el
último mensaje. Ver [pruebas y despliegue](docs/ai-chat-qa.md); la validación con
el modelo real sigue pendiente del saldo de Z.AI.

API REST multi-tenant construida con FastAPI, PostgreSQL y SQLAlchemy para
inventario, usuarios, clientes y tareas.

## Inicio rápido local

Requisitos: Python 3.11+, PostgreSQL 16 y un entorno virtual.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Complete los valores obligatorios de `.env`, cree la base configurada y ejecute:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

La documentación interactiva queda en `http://localhost:8000/docs`. Los probes
`GET /health` y `GET /ready` permiten comprobar el proceso y la conexión a la
base de datos, respectivamente.

## Inicio con Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

El contenedor publica la API en el puerto 80. La primera ejecución crea las
tablas globales y cada empresa recibe un esquema PostgreSQL independiente.

## Variables de entorno

| Variable | Obligatoria | Uso |
|---|---|---|
| `DB_SERVER` | sí | Host de PostgreSQL (`localhost` local, `db` en Compose) |
| `DB_DATABASE` | sí | Nombre de la base |
| `DB_USERNAME` | sí | Usuario de la base |
| `DB_PASSWORD` | sí | Contraseña de la base |
| `DB_PORT` | no | Puerto, 5432 por defecto |
| `DB_POOL_SIZE` | no | Conexiones fijas del pool por proceso, 20 por defecto; debe ser al menos 1 |
| `DB_MAX_OVERFLOW` | no | Conexiones extra sobre el pool, 20 por defecto; debe ser 0 o mayor. No se admiten pools ilimitados. La suma con `DB_POOL_SIZE` es también el máximo de solicitudes que la API atiende a la vez; las demás esperan turno |
| `DB_POOL_TIMEOUT` | no | Segundos de espera por una conexión libre, 30 por defecto |
| `DB_POOL_RECYCLE` | no | Segundos antes de renovar una conexión, 3600 por defecto |
| `SECRET_KEY` | sí | Firma JWT; use un valor aleatorio largo |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Duración de access tokens |
| `SUPERADMIN_EMAIL` | sí | Correo del superadministrador inicial |
| `SUPERADMIN_USERNAME` | sí | Usuario del superadministrador inicial |
| `SUPERADMIN_PASSWORD` | sí | Contraseña inicial del superadministrador |
| `SMTP_USERNAME` | sí | Cuenta de envío de invitaciones y recuperación |
| `SMTP_PASSWORD` | sí | Credencial SMTP |
| `FRONTEND_URL` | sí | Origen CORS y base de enlaces enviados por correo |
| `DEMO_SEED_ENABLED` | no | Habilita usuarios demo; desactivado por defecto |
| `DEMO_USER_PASSWORD` | si activa demo | Contraseña de usuarios demo |

No suba `.env` al repositorio. `.env.example` solo contiene valores de ejemplo.

## HTTPS en producción

Todo el endurecimiento de transporte está apagado por defecto, para que el
desarrollo local y las pruebas sigan funcionando sobre HTTP plano. Se enciende
por variables de entorno.

| Variable | Efecto |
|---|---|
| `FORCE_HTTPS` | Redirige HTTP a HTTPS y envía `Strict-Transport-Security` |
| `ALLOWED_HOSTS` | Lista separada por comas de hosts aceptados. Vacío desactiva la validación |
| `HSTS_MAX_AGE` | Duración de HSTS en segundos. Por defecto 63072000, dos años |

Las cabeceras `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
`Content-Security-Policy`, `Cross-Origin-Resource-Policy: same-origin` y
`Cache-Control: no-store` se envían siempre, incluidos errores 500, preflights CORS
y rechazos de host. HSTS se envía únicamente en respuestas HTTPS con
`FORCE_HTTPS=true`.

La CSP de la API bloquea recursos y framing. `/docs`, `/redoc` y el callback OAuth
usan una política específica: permiten los CDN de la documentación y scripts
inline autorizados por hash SHA-256, sin `unsafe-inline` ni `unsafe-eval` para
scripts. Las interfaces de documentación requieren estilos inline. La política
protege el contenido servido por este backend; el frontend debe enviar su propia
CSP.

CORS permite `FRONTEND_URL` y los puertos locales 5173/3000 por defecto. En
producción configure `CORS_ORIGINS=https://app.example.com` (lista separada por
comas de orígenes exactos, sin paths ni barra final): reemplaza los defaults y
excluye localhost. Un valor vacío niega todos los orígenes. Solo se aceptan
GET/POST/PUT/PATCH/DELETE/OPTIONS y los headers Authorization/Content-Type,
además de los headers simples CORS. CORS también cubre los errores 500, y no
sustituye autenticación ni autorización.

La evidencia de mitigaciones y el comparativo ZAP del Sprint 9 están en
[docs/security/sprint9/README.md](docs/security/sprint9/README.md).

Dos detalles que importan al desplegar:

- **HSTS solo sale con `FORCE_HTTPS` encendido.** Enviarlo mientras el sitio
  todavía responde por HTTP deja al navegador negándose a abrir el host por
  `http://`, y eso no se revierte desde el servidor.
- **Detrás de un proxy que termina TLS, uvicorn necesita `--proxy-headers`.**
  Sin eso ve HTTP plano, no reconoce `X-Forwarded-Proto` y la redirección entra
  en bucle. El `CMD` del Dockerfile ya lo pasa, junto con
  `--forwarded-allow-ips`.

Activar `ALLOWED_HOSTS` antes de exponer el servicio: sin lista, el host del
request no se valida.

## Matriz de permisos

Cuatro roles, jerárquicos: `employee` < `manager` < `admin` < `superadmin`.
Cada nivel hereda todo lo del anterior.

| Rol | Alcance |
|---|---|
| `employee` | Lectura de todo el tenant y CRUD de sus propias tareas |
| `manager` | Además: crear y editar productos, proveedores y clientes; movimientos; importaciones; ventas |
| `admin` | Además: desactivar y eliminar registros; gestión de usuarios y roles; reportes |
| `superadmin` | Además: registro de empresas y consultas entre empresas |

Detalle por endpoint. «Autenticado» significa cualquier usuario con sesión
válida, es decir también `employee`.

| Endpoint | Rol mínimo |
|---|---|
| `POST /api/v1/auth/login`, `/password/*` | Público |
| `GET /`, `GET /health`, `GET /ready` | Público |
| `POST /api/v1/auth/register` | `superadmin` estricto |
| `GET /api/v1/companies` | `superadmin` estricto |
| `POST /api/v1/auth/employees`, `GET /api/v1/auth/employees` | `admin` |
| `POST /api/v1/auth/invitations/resend` | `admin` |
| `GET/PUT/PATCH/DELETE /api/v1/users/*` | `admin` |
| `GET /api/v1/roles` | `admin` |
| `GET /api/v1/reports/*` | `admin` |
| `GET /api/v1/inventory/products`, `/suppliers`, `/movements`, `/alerts` | Autenticado |
| `GET /api/v1/inventory/suppliers/{id}`, `/supplier-products` | Autenticado |
| `GET /api/v1/inventory/analytics/*`, `/metrics`, `/history` | `manager` |
| `POST /api/v1/inventory/products`, `/suppliers`, `/movements`, `/products/import` | `manager` |
| `PUT /api/v1/inventory/suppliers/{id}` | `manager` |
| `PATCH /api/v1/inventory/products/{id}/status`, `/suppliers/{id}/status` | `admin` |
| `DELETE /api/v1/inventory/suppliers/{id}` | `admin` |
| `GET /api/v1/commercial/clients`, `/clients/{id}` | Autenticado |
| `GET /api/v1/commercial/sales/{id}`, `/clients/{id}/purchases` | Autenticado |
| `GET /api/v1/analytics/*` | `manager` o `admin` estricto |
| `POST /api/v1/ai/analysis` | `manager` o `admin` estricto |
| `POST /api/v1/ai/chat`, `GET /api/v1/ai/conversations`, `GET/DELETE /api/v1/ai/conversations/{id}` | `manager` o `admin` estricto; conversaciones propias |
| `POST /api/v1/commercial/clients`, `/sales` | `manager` |
| `POST /api/v1/commercial/sales/{id}/void` | `manager` |
| `PUT /api/v1/commercial/clients/{id}` | `manager` |
| `PATCH /api/v1/commercial/clients/{id}/status` | `admin` |
| `DELETE /api/v1/commercial/clients/{id}` | `admin` |
| `GET /api/v1/commercial/tax-configuration` | Autenticado |
| `PUT /api/v1/commercial/tax-configuration` | `admin` |
| `GET/POST/PUT/PATCH/DELETE /api/v1/tasks/*` | Autenticado, y solo sobre tareas propias |

Dos reglas del dependency que conviene tener presentes:

- `require_role("manager")` admite además `admin` y `superadmin`, porque
  `ELEVATED_ROLES` pasa por encima de cualquier lista de roles. Es lo que hace
  que la jerarquía funcione sin enumerar roles en cada endpoint.
- Por lo anterior, `require_role("superadmin")` **no** restringe a superadmin:
  un `admin` también pasa. Para eso está `require_role("superadmin",
  strict=True)`, que compara contra la lista exacta y no aplica la jerarquía.
- `require_role()` sin argumentos deja pasar a cualquier usuario autenticado.
  Es intencional para las lecturas del tenant, pero no es un guard de rol.

Las restricciones por empresa son independientes del rol: `get_user_schema_name`
resuelve el esquema desde `current_user.company`, así que ningún endpoint de
inventario o comercial puede leer datos de otro tenant, sea cual sea su rol.
En las tablas globales el filtro lo hacen los services: un usuario de otra empresa
responde 404, igual que uno inexistente. Un usuario de una empresa inactiva
recibe 403 en todas las rutas y tampoco puede iniciar sesión.

La tabla anterior tiene su copia ejecutable en `ROUTE_POLICY`, dentro de
`tests/security_helpers.py`. `tests/test_security_route_inventory.py` la compara
con las rutas que la aplicación registra de verdad: falla si aparece un endpoint
sin clasificar, si queda una entrada de una ruta que ya no existe o si el guard de
una ruta no coincide con su política. Al agregar un endpoint hay que actualizar
las dos, la tabla del README y `ROUTE_POLICY`.

La revisión de seguridad de septiembre de 2026, con sus hallazgos, correcciones y
recomendaciones pendientes, está en
[docs/revision-seguridad.md](docs/revision-seguridad.md).

## Desactivación de clientes y proveedores

Clientes y proveedores no se borran: se desactivan. El registro conserva su
historial y deja de aparecer en los listados por defecto.

| Operación | Cliente | Proveedor |
|---|---|---|
| Desactivar | `PATCH /commercial/clients/{id}/status` con `is_active=false` | `PATCH /inventory/suppliers/{id}/status` |
| Eliminar (soft delete) | `DELETE /commercial/clients/{id}` | `DELETE /inventory/suppliers/{id}` |
| Listar por estado | `GET /commercial/clients?is_active=` | `GET /inventory/suppliers?is_active=` |

Ambos exigen rol admin, y ambos responden 400 si el registro ya está en el
estado solicitado.

**Qué bloquea la desactivación.** Solo las relaciones en curso, nunca el
historial:

- Un proveedor no se desactiva mientras tenga productos activos asociados.
- Un cliente no se desactiva mientras tenga ventas en estado `borrador`. Las
  ventas `completada` y `anulada` no lo impiden: conservarlas es justamente el
  motivo del soft delete.

**Nombres y correos.** Solo los registros activos reservan su nombre y su
correo, en clientes y en proveedores por igual. Desactivar libera ambos, de modo
que el nombre puede reutilizarse. Como contrapartida, reactivar falla con 400 si
alguien tomó ese nombre mientras tanto; hay que renombrar antes de reactivar.

Los índices únicos de `cliente` (nombre y correo) y de `proveedor` (nombre) son
parciales sobre `is_active` y no distinguen mayúsculas, así que la regla se
sostiene también a nivel de base y no solo en el service: si dos solicitudes
pasan la validación a la vez, la segunda responde 400. Al arrancar, la API crea
o actualiza estos índices en las empresas existentes; si una empresa ya tiene
duplicados activos, la omite y deja un warning en el log, y el índice se crea en
el siguiente arranque después de resolverlos.

**Filtro de estado.** `?is_active=true` y `?is_active=false` filtran por estado
exacto; omitirlo muestra solo los activos. En clientes se conserva `active_only`
como alias histórico y está marcado como deprecado: `active_only=false` equivale
a no filtrar.

## Contrato consumido por frontend

La especificación completa está en `/docs`. Estos son los grupos principales:

- `/api/v1/auth`: registro, inicio de sesión, invitaciones y contraseñas.
- `/api/v1/companies`: listado de empresas para superadministración.
- `/api/v1/users` y `/api/v1/roles`: administración de empleados y roles.
- `/api/v1/inventory`: productos, proveedores, movimientos y analítica.
- `/api/v1/commercial`: clientes.
- `/api/v1/tasks`: tareas personales del usuario autenticado.
- `/api/v1/reports`: reportes de inventario, movimientos y alertas.

### Empleados: `PUT /api/v1/users/{id}`

Actualiza `username`, `role_id` e `is_active` en una sola transacción. Valida todo
antes de escribir: si un campo se rechaza, no se aplica ninguno. Así el frontend
puede guardar rol y estado en una sola llamada en lugar de un PUT seguido de un
PATCH, que dejaba el rol cambiado si el segundo fallaba.
`PATCH /api/v1/users/{id}/status` sigue disponible.

- Un admin no puede cambiar su propio rol ni su propio estado (400).
- `username` se guarda sin espacios al inicio ni al final y debe tener de 1 a 50
  caracteres (422). Es único entre todas las empresas: un nombre tomado responde
  400, también cuando dos solicitudes lo piden a la vez.
- Al crear empleados (`POST /api/v1/auth/employees`) rige lo mismo para `username`
  y para el correo.

### Importación de productos: `POST /api/v1/inventory/products/import`

Requiere rol manager o superior. Recibe un archivo en el campo `file` de un
formulario multipart.

| Regla | Valor |
|---|---|
| Formatos | `.csv` en UTF-8 o `.xlsx` (se lee la primera hoja) |
| Tamaño máximo | 5 MB y 5000 filas |
| Columnas obligatorias | `sku`, `nombre` |
| Columnas opcionales | `descripcion`, `precio_venta`, `stock_minimo`, `unidad_medida`, `proveedor_id` |
| Encabezados | Sin distinción de mayúsculas; cualquier otra columna se rechaza |
| Stock inicial | 0; las existencias se cargan después con movimientos |
| Valores por defecto | `precio_venta` y `stock_minimo` en 0, `unidad_medida` en `unidad` |
| SKU | Se guarda en minúsculas, igual que al crear un producto; los repetidos se detectan sin distinguir mayúsculas |

La importación es todo o nada: si una fila tiene errores no se crea ningún
producto. La respuesta exitosa es `{"inserted": n, "products": [...]}`. Un rechazo
responde 400 con el contrato de error habitual; `code` indica el motivo general y
`errors` trae un elemento por problema, con `row`, `column`, `code` y `message`.
`row` empieza en 2 para la primera fila de datos; las filas vacías se omiten y no
cuentan.

| `code` general | Motivo |
|---|---|
| `empty_file` | Archivo vacío o sin filas de datos |
| `file_too_large` | Más de 5 MB |
| `import_too_large` | Más de 5000 filas |
| `unsupported_format` | Extensión distinta de `.csv` o `.xlsx` |
| `invalid_format` | CSV que no es UTF-8 o XLSX dañado |
| `invalid_columns` | Falta una columna obligatoria (`missing_column`) o sobra una (`unexpected_column`) |
| `invalid_rows` | Errores por fila, detallados en `errors` |

Códigos por fila: `required`, `duplicate_sku` (repetido en el archivo),
`existing_sku` (ya existe en la empresa), `invalid_decimal`, `negative_decimal`,
`decimal_too_large`, `too_many_decimals`, `invalid_uuid`, `supplier_not_found`,
`supplier_inactive` y `csv_injection` (celdas que empiezan con `=`, `+`, `-` o `@`).

### Movimientos manuales: `POST /api/v1/inventory/movements`

Requiere rol manager o superior. Cada movimiento actualiza el stock y las alertas
en la misma transacción, y el stock nunca queda negativo (400).

| Suman | Restan |
|---|---|
| `entrada_compra`, `entrada_manual`, `ajuste_positivo`, `devolucion_cliente` | `salida_manual`, `ajuste_negativo`, `devolucion_proveedor` |

- `salida_venta` solo la registran las ventas, y `referencia_tipo` y
  `referencia_id` solo los fijan las ventas y sus anulaciones. Enviarlos en un
  movimiento manual responde 400, para que un movimiento manual no pueda pasar por
  una venta.
- Los ajustes (`ajuste_positivo`, `ajuste_negativo`) exigen `motivo`; sin él la
  respuesta es 422. En los demás tipos el motivo es opcional.
- Un producto inactivo no se vende ni acepta movimientos manuales (400), salvo
  ajustes: así se corrige o se da de baja el stock que le quedó. Las anulaciones
  de ventas también le devuelven su stock.

### Reportes — `/api/v1/reports`

Todos los endpoints de reportes requieren rol admin o superior.

| Método | Path | Notas |
|---|---|---|
| GET | `/history` | Historial de reportes generados. `?limit=` entre 1 y 100 (default 20) |
| GET | `/inventario` | Stock actual. Filtros `?product_id=`, `?is_active=`, `?only_low_stock=` |
| GET | `/movimientos` | Movimientos del período. Filtros `?period=`, `?start_date=`, `?end_date=`, `?product_id=`, `?movement_type=` |
| GET | `/alertas` | Alertas del período. Filtros `?period=`, `?start_date=`, `?end_date=`, `?open_only=` |

Los tres reportes aceptan `?format=csv` (default) o `?format=pdf` y responden con el
archivo como descarga (`Content-Disposition: attachment`), no con JSON.

`period` acepta `7d`, `30d` (default), `90d`, `6m`, `12m`, `ytd` o `custom`; con `custom` hay
que enviar `start_date` y `end_date`, de lo contrario la API responde 400.

Cada generación queda registrada en la tabla `reporte` del esquema de la empresa y se
consulta con `GET /history`. El archivo no se almacena en el servidor — se transmite
directamente al cliente, por lo que `ruta_archivo` siempre viene en `null`.

El registro persistente de auditoría de reportes contiene `id`, `tipo`, `periodo_inicio`,
`periodo_fin`, `formato`, `estado`, `generado_por_usuario_id`, `fecha_generacion` y
`ruta_archivo`. Los tipos registrados son `inventario`, `movimientos`, `alertas` y
`tributario`. `estado` queda en `generado` cuando la generación y el registro terminan
correctamente; `ruta_archivo` permanece en `null` porque el archivo se transmite directamente
al cliente y no se almacena en el servidor.

`id` identifica el registro; `tipo` y `formato` describen el reporte; los campos de período
conservan el rango cuando fue solicitado; `generado_por_usuario_id` identifica al actor;
`fecha_generacion` conserva el momento de generación; y `estado` refleja el resultado
persistido. No existe un identificador de correlación independiente del `id` del registro.

El registro se inserta después de renderizar el reporte y se confirma con la misma sesión.
Si falla la inserción del historial, la transacción se revierte y la API devuelve un error
genérico. `GET /api/v1/reports/history` requiere autenticación y rol `admin` o superior,
y resuelve la tabla `reporte` desde la empresa del usuario autenticado; el cliente no
selecciona el esquema mediante el request.

Este historial de reportes es el único mecanismo persistente de auditoría identificado.
Los mensajes emitidos mediante `logger` son logs operativos y no constituyen por sí mismos
un historial consultable desde la API. Actualmente no hay un registro persistente general
documentado para inicios de sesión, fallos de autenticación, usuarios, roles, clientes,
ventas, inventario, configuración tributaria, documentos fiscales o importaciones.

El CSV se genera con BOM UTF-8 para que Excel muestre bien los acentos, y las celdas que
empiezan con `=`, `+`, `-` o `@` se escapan para evitar inyección de fórmulas.

### Reglas tributarias y cálculo de impuestos

#### Configuración tributaria
La configuración tributaria pertenece al esquema de cada tenant (tabla `configuracion_tributaria`).
- **Consulta**: Cualquier usuario autenticado puede consultar la tasa actual con `GET /api/v1/commercial/tax-configuration`.
- **Actualización**: Solo los roles `admin` y `superadmin` pueden modificarla mediante `PUT /api/v1/commercial/tax-configuration`.
- **Tasa permitida**: La `tasa_impuesto` debe ser un valor decimal entre `0.00` y `100.00` con hasta 2 decimales.
- **Compatibilidad**: Tenants sin configuración explícita utilizan una tasa predeterminada de `0.00` (sin recargo fiscal).

#### Reglas de cálculo en ventas
Al registrar una venta mediante `POST /api/v1/commercial/sales`:
1. **Subtotal**: Suma de las líneas de detalle (`cantidad * precio_unitario`), redondeado cada ítem con `ROUND_HALF_UP` a 2 decimales.
2. **Descuento**: Monto descontado del subtotal (`0 <= descuento <= subtotal`).
3. **Impuesto aplicable**:
   - Para operaciones gravadas (`es_exenta=false`), se calcula: `impuesto = round(subtotal * (tasa_impuesto / 100))`.
   - Para operaciones exentas (`es_exenta=true`), el impuesto es forzado a `0.00` sin alterar el registro histórico de la tasa aplicable.
4. **Total final**: `total = subtotal - descuento + impuesto`.
5. **Redondeo monetario**: Se utiliza redondeo aritmético simétrico (`ROUND_HALF_UP`) con precisión a centavos (`0.01`).
6. **Almacenamiento del desglose**: La venta almacena `subtotal`, `descuento`, `impuesto`, `tasa_impuesto`, `es_exenta` y `total` para auditoría e histórico inmutable.

#### Anulación de ventas

`POST /api/v1/commercial/sales/{sale_id}/void` con `{"motivo": "..."}` anula una
venta completada. Requiere rol manager o superior.

- `motivo` es obligatorio, de 1 a 200 caracteres sin contar los espacios al inicio
  y al final.
- La venta no se borra: pasa a `estado = anulada` y guarda `motivo_anulacion`,
  `anulada_por` (el usuario) y `anulada_en`. Sus líneas, importes y movimientos
  `salida_venta` quedan como estaban.
- En la misma transacción, el stock de cada línea vuelve al producto con un
  movimiento `devolucion_cliente` cuyo `referencia_tipo` es `anulacion_venta`,
  cuyo `referencia_id` es la venta y cuyo `motivo` es el de la anulación. Las
  alertas de stock se recalculan.
- También se anulan ventas con productos que se desactivaron después: la anulación
  corrige el historial y devuelve su stock.
- Una venta ya anulada responde 400, también cuando dos anulaciones llegan a la vez:
  solo una se aplica. Una venta inexistente o de otra empresa responde 404.
- Las métricas, los reportes y el chat cuentan solo ventas completadas, así que una
  venta anulada deja de sumar en ellos.

### Tareas

Los estados válidos son `pendiente`, `en_progreso`, `completada` y `cancelada`;
las prioridades son `baja`, `media`, `alta` y `urgente`. Todas las consultas se
restringen al usuario y al esquema tenant autenticados.

| Método | Path | Descripción |
|---|---|---|
| GET | `/api/v1/tasks` | Lista y filtra por `estado`, `prioridad` o `search` |
| POST | `/api/v1/tasks` | Crea una tarea pendiente |
| GET | `/api/v1/tasks/{task_id}` | Obtiene una tarea propia |
| PUT | `/api/v1/tasks/{task_id}` | Actualiza los campos enviados |
| PATCH | `/api/v1/tasks/{task_id}/status` | Cambia el estado |
| DELETE | `/api/v1/tasks/{task_id}` | Elimina una tarea propia |

## Pruebas

```bash
pytest -q
```

Las pruebas no requieren un PostgreSQL real: reemplazan la inicialización y las
dependencias de persistencia cuando corresponde.

### Pruebas de carga

`tests/load/` tiene el escenario de k6, el script que llena una base local
desechable y el que resume los resultados. El método, la línea base y las
optimizaciones del sprint 9 están en [docs/rendimiento.md](docs/rendimiento.md).

### Análisis inteligente — `/api/v1/ai`

El endpoint autenticado `POST /analysis` utiliza la API compatible con OpenAI de
Z.AI. Crear una clave en [la consola de Z.AI](https://z.ai/manage-apikey/apikey-list)
y configurar:

```env
ZAI_API_KEY=
ZAI_MODEL=glm-5.3-flash
ZAI_BASE_URL=https://api.z.ai/api/paas/v4
ZAI_TIMEOUT_SECONDS=30
```

`glm-5.3-flash` es una opción gratuita publicada por Z.AI; los límites y precios
pueden cambiar, por lo que deben comprobarse en su consola. Si no se configura
`ZAI_API_KEY`, el endpoint responde `503` sin impedir el arranque del resto de la
API. Nunca se registra ni se devuelve la clave.

El body acepta `scope=inventory|sales|catalog|business`, `period`, `start_date`,
`end_date`, `product_id`, `supplier_id`, `client_id`, `customer_type` y una
`question` opcional. Solo se envían métricas agregadas del tenant autenticado; no se
envían correos, nombres de usuarios, credenciales ni el nombre del esquema. La
respuesta siempre se valida con la estructura `summary`, `insights` y
`recommendations`. Z.AI es un tercero: antes de usar datos reales se deben revisar
sus términos, retención y tratamiento de datos vigentes.

Respuestas operativas: `400/422` para filtros inválidos, `401/403` para problemas de
acceso, `502` para una respuesta inválida del proveedor y `503` para clave ausente,
credenciales inválidas, rate limit o indisponibilidad temporal.

La integración externa no se ejecuta durante la suite normal. Para comprobar una
llamada real con la clave del `.env`, ejecutar explícitamente:

```powershell
$env:RUN_ZAI_INTEGRATION_TEST="1"
python -m pytest tests/test_zai.py -k live -v
```


### Permisos y filtros del análisis de ventas

`/api/v1/analytics/*` y `/api/v1/ai/analysis` requieren el rol exacto `manager` o
`admin`, igual que el chat, y consultan únicamente la empresa activa del usuario.
Las métricas y tendencias de ventas aceptan `product_id` y `supplier_id`; cuando
se proporcionan ambos, se aplica su intersección. El análisis usa los mismos
filtros en métricas, tendencias y ranking.

Con estos filtros se suman únicamente los subtotales de las líneas seleccionadas
y se cuenta cada venta coincidente una sola vez. Los descuentos e impuestos de la
venta se prorratean según `subtotal seleccionado / subtotal de la venta`, con
redondeo a centavos por venta (Decimal, mitad al par). Las ventas netas filtradas
son subtotal seleccionado menos descuento asignado más impuesto asignado; el
ticket promedio usa ese importe y el número de ventas coincidentes. Sin filtros,
se conservan los importes completos registrados en la venta. Una venta con
subtotal cero no tiene base monetaria de reparto y recibe cargos asignados cero.
El ranking muestra subtotales de líneas antes del prorrateo, y el contexto enviado
al proveedor explica esta diferencia. Consultas separadas pueden diferir por un
centavo al recombinar asignaciones redondeadas.

Los errores de validación HTTP mantienen `message`, `code` y `errors`; cada error
incluye `type`, `loc` y `msg`. No se devuelven objetos de excepción ni la entrada
original. Los validadores de preguntas vacías y filtros incompatibles siguen
activos y responden 422.

## Sprint 10: auditoría y consultas de movimientos paginadas

`GET /api/v1/audit/events` permite a administradores consultar acciones críticas
solo de su empresa activa. Devuelve `{items, next_cursor}` y acepta `limit` (1–100),
`cursor`, `action` y `actor_id`. Los eventos se escriben dentro de la transacción
del cambio; no contienen contraseñas, tokens ni cuerpos completos. El catálogo y
los límites de cobertura están en [auditoría del Sprint 10](docs/security/sprint10/README.md).

`GET /api/v1/inventory/movements/page` devuelve `{items, next_cursor}` con `limit`
(1–500), filtro `product_id` y cursor por fecha/ID. La ruta anterior `/movements`
conserva su lista completa. El frontend debe adoptar la ruta nueva para reducir
el volumen de respuesta. Ver [mediciones y reproducción](docs/performance/sprint10/README.md).

El bootstrap crea la tabla `audit_event` y los índices de paginación para tenants
existentes. Planificar la migración antes de levantar réplicas: crear índices
puede bloquear escrituras en tablas grandes. No se activa multi-worker por
defecto porque el chat y el rate limit de recuperación siguen usando memoria por
proceso. El tamaño máximo del pool se multiplica por la cantidad de workers.

El workflow `Dependency audit` revisa dependencias de ejecución/desarrollo con
pip-audit y conserva JSON aun si falla. La primera auditoría detectó vulnerabilidades
existentes; el detalle y la remediación pendiente están documentados. No se
suprimen alertas para conseguir un check verde ni se modifican reglas de merge.
